from flask import Flask, render_template, request
import logging
import os
import json
import requests
import google.generativeai as genai
from typing import Dict, Any, Optional, List

app = Flask(__name__)

# --- Configuration ---
app.config['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY')
app.config['BIRDEYE_API_KEY'] = os.environ.get('BIRDEYE_API_KEY')

# --- Initialisation de l'API Gemini ---
try:
    genai.configure(api_key=app.config['GEMINI_API_KEY'])
    model = genai.GenerativeModel('gemini-1.5-flash')
    logging.info("INFO: API Gemini configurée avec succès")
except Exception as e:
    logging.error(f"ERREUR: La configuration de l'API Gemini a échoué - {e}")
    model = None

# --- Configuration du Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Filtres Jinja2 pour le Template ---
@app.template_filter()
def format_price(value: float) -> str:
    try:
        value = float(value)
        if value < 0.00001:
            return f"${value:,.10f}".rstrip('0').rstrip('.')
        return f"${value:,.6f}".rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return "N/A"

@app.template_filter()
def format_market_cap(value: float) -> str:
    try:
        value = float(value)
        if value >= 1_000_000_000:
            return f"${value/1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"${value/1_000_000:.2f}M"
        elif value >= 1_000:
            return f"${value/1_000:.2f}K"
        return f"${value:,.2f}"
    except (ValueError, TypeError):
        return "N/A"

# --- Services ---
class BirdeyeService:
    BASE_URL = "https://public-api.birdeye.so"

    @staticmethod
    def get_token_overview(token_address: str) -> Optional[Dict[str, Any]]:
        """Récupère les données complètes d'un token depuis Birdeye."""
        url = f"{BirdeyeService.BASE_URL}/defi/token_overview?address={token_address}"
        headers = {"X-API-KEY": app.config['BIRDEYE_API_KEY']}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data.get('data') if data.get('success') else None
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_token_overview): {e}")
            return None

    @staticmethod
    def get_trending_tokens() -> tuple[List[Dict[str, Any]], Optional[str]]:
        """Récupère les tokens les plus échangés sur les dernières 24h."""
        url = f"{BirdeyeService.BASE_URL}/defi/tokenlist?sort_by=v24hUSD&sort_type=desc"
        headers = {"X-API-KEY": app.config['BIRDEYE_API_KEY']}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return (data.get('data', {}).get('tokens', [])[:10], None) if data.get('success') else ([], "Réponse invalide de l'API")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_trending_tokens): {e}")
            return [], str(e)

class AIService:
    @staticmethod
    def analyze_token(token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyse les données du token avec le modèle Gemini AI."""
        if not model:
            return {"error": "Modèle IA non initialisé."}

        prompt = f"""
        Analyse ce token Solana avec les données suivantes :
        - Nom: {token_data.get('name', 'N/A')}
        - Symbole: {token_data.get('symbol', 'N/A')}
        - Prix Actuel (USD): {token_data.get('price', 'N/A')}
        - Market Cap (USD): {token_data.get('mc', 'N/A')}
        - Variation 24h (%): {token_data.get('priceChange24h', 0)}

        Effectue une analyse de risque concise.

        Retourne ta réponse UNIQUEMENT en format JSON valide, sans texte additionnel.
        L'objet JSON doit contenir ces clés exactes :
        - "total_score": Un score de confiance global sur 100 (0=très risqué, 100=très fiable).
        - "final_verdict": Un verdict court et direct parmi : "BUY NOW", "POTENTIAL BUY", "HOLD", "WAIT", "HIGH-RISK".
        - "probability": La probabilité estimée (en entier) d'une tendance positive à court terme.
        - "summary": Un résumé d'une phrase expliquant ton raisonnement.
        """
        try:
            response = model.generate_content(prompt)
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(cleaned_response)
        except Exception as e:
            logging.error(f"Erreur analyse Gemini: {e}")
            return {
                "total_score": 0, "final_verdict": "ERROR", "probability": 0,
                "summary": "L'analyse par l'IA a échoué. Veuillez réessayer."
            }

# --- Routes Flask ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/tendances")
def tendances():
    if not app.config['BIRDEYE_API_KEY']:
        return render_template("tendances.html", error="Clé API Birdeye non configurée.")

    trending_data, error = BirdeyeService.get_trending_tokens()
    
    transformed_data = [{
        'logo': token.get('logoURI'),
        'name': token.get('name'),
        'symbol': token.get('symbol'),
        'price_usd': token.get('price'),
        'price_change_24h_percent': token.get('priceChange24h'),
        'token_address': token.get('address')
    } for token in trending_data]

    return render_template("tendances.html", trending_data=transformed_data, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    token_address = request.form.get("token", "").strip()
    if not token_address:
        return render_template("results.html", results=[{"error": "L'adresse du token est requise."}])

    token_data = BirdeyeService.get_token_overview(token_address)

    if not token_data:
        return render_template("results.html", results=[{"error": "Token non trouvé ou erreur API Birdeye."}])

    # Préparation des données pour le template et l'IA
    result = {
        "token": token_address,
        "token_name": token_data.get("name", "N/A"),
        "token_symbol": token_data.get("symbol", "N/A"),
        "current_price": token_data.get("price"),
        "price_change_percent": token_data.get("priceChange24h"),
        "market_cap": token_data.get("mc"), # mc = Market Cap
        "dexscreener_url": f"https://dexscreener.com/solana/{token_address}?embed=1&theme=dark&info=0"
    }

    # Analyse par l'IA
    ai_analysis = AIService.analyze_token(token_data)
    result["ai_analysis"] = ai_analysis
    result["total_score"] = ai_analysis.get("total_score", 0)

    return render_template("results.html", results=[result])

# --- Gestionnaires d'Erreurs ---
@app.errorhandler(404)
def not_found(e):
    return "<h1>Page non trouvée</h1>", 404

@app.errorhandler(500)
def server_error(e):
    logging.error(f"Erreur Serveur 500: {e}")
    return "<h1>Erreur interne du serveur</h1>", 500

if __name__ == "__main__":
    app.run(debug=True)
