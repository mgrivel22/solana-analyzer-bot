from flask import Flask, render_template, request
import logging
import os
import json
import requests # Ajout de requests pour les appels directs à l'API
import google.generativeai as genai
from moralis import sol_api
from typing import Dict, Any, Optional

app = Flask(__name__)

# --- Configuration ---
app.config['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY')
app.config['MORALIS_API_KEY'] = os.environ.get('MORALIS_API_KEY')

# --- Initialisation des APIs ---
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
        return f"${value:,.10f}".rstrip('0').rstrip('.')
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
class MoralisService:
    @staticmethod
    def get_token_price_data(token_address: str) -> Optional[Dict[str, Any]]:
        """Récupère les données de prix pour un token SPL."""
        try:
            params = {"network": "mainnet", "address": token_address}
            return sol_api.token.get_token_price(api_key=app.config['MORALIS_API_KEY'], params=params)
        except Exception as e:
            logging.error(f"Erreur Moralis (get_token_price_data): {e}")
            return None

    @staticmethod
    def get_token_metadata(token_address: str) -> Optional[Dict[str, Any]]:
        """Récupère les métadonnées (supply, etc.) pour un token SPL."""
        try:
            params = {"network": "mainnet", "addresses": [token_address]}
            metadata = sol_api.token.get_token_metadata(api_key=app.config['MORALIS_API_KEY'], params=params)
            return metadata[0] if metadata else None
        except Exception as e:
            logging.error(f"Erreur Moralis (get_token_metadata): {e}")
            return None

    @staticmethod
    def get_trending_tokens() -> tuple:
        """
        CORRECTION: Utilise un appel direct à l'API Moralis Deep Index
        car la fonction n'est pas disponible dans le module sol_api du SDK.
        """
        url = "https://deep-index.moralis.io/api/v2.2/tokens/trending"
        headers = {
            "accept": "application/json",
            "X-API-Key": app.config['MORALIS_API_KEY']
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            # L'API renvoie un objet avec des clés pour chaque chaîne, nous voulons Solana.
            solana_trending = response.json().get("solana", [])
            return solana_trending[:10], None
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Moralis (get_trending_tokens): {e}")
            return [], str(e)

class AIService:
    @staticmethod
    def analyze_token(token_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyse les données du token avec le modèle Gemini AI."""
        if not model:
            return {"error": "Modèle IA non initialisé."}

        prompt = f"""
        Analyse ce token Solana avec les données suivantes :
        - Nom: {token_data.get('token_name', 'N/A')}
        - Symbole: {token_data.get('token_symbol', 'N/A')}
        - Prix Actuel (USD): {token_data.get('current_price', 'N/A')}
        - Market Cap (USD): {token_data.get('market_cap', 'N/A')}
        - Variation 24h (%): {token_data.get('price_change_percent', 'N/A')}

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
    if not app.config['MORALIS_API_KEY']:
        return render_template("tendances.html", error="Clé API Moralis non configurée.")

    trending_data, error = MoralisService.get_trending_tokens()
    
    # Transformation des données pour correspondre au template
    transformed_data = [{
        'logo': token.get('image_url'),
        'name': token.get('name'),
        'symbol': token.get('symbol'),
        'price_usd': token.get('price_usd'),
        'price_change_24h_percent': token.get('price_change_24h_percent'),
        'token_address': token.get('address')
    } for token in trending_data]

    return render_template("tendances.html", trending_data=transformed_data, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    token_address = request.form.get("token", "").strip()
    if not token_address:
        return render_template("results.html", results=[{"error": "L'adresse du token est requise."}])

    price_data = MoralisService.get_token_price_data(token_address)
    metadata = MoralisService.get_token_metadata(token_address)

    if not price_data or "usdPrice" not in price_data:
        return render_template("results.html", results=[{"error": "Token non trouvé ou erreur API Moralis."}])

    # Calcul du Market Cap
    market_cap = 0
    try:
        if metadata and metadata.get('totalSupply') and metadata.get('decimals'):
            total_supply = int(metadata['totalSupply'])
            decimals = int(metadata['decimals'])
            real_supply = total_supply / (10 ** decimals)
            market_cap = real_supply * float(price_data['usdPrice'])
    except (ValueError, TypeError) as e:
        logging.error(f"Erreur de calcul du market cap: {e}")

    # Préparation des données pour le template et l'IA
    result = {
        "token": token_address,
        "token_name": price_data.get("tokenName", "N/A"),
        "token_symbol": price_data.get("tokenSymbol", "N/A"),
        "current_price": price_data.get("usdPrice", 0),
        "price_change_percent": price_data.get("usdPriceChange24h", 0),
        "market_cap": market_cap,
        "pair_address": price_data.get("pairAddress", token_address),
        "dexscreener_url": f"https://dexscreener.com/solana/{price_data.get('pairAddress', '')}?embed=1&theme=dark&info=0"
    }

    # Analyse par l'IA
    ai_analysis = AIService.analyze_token(result)
    result["ai_analysis"] = ai_analysis
    result["total_score"] = ai_analysis.get("total_score", 0)

    return render_template("results.html", results=[result])

# --- Gestionnaires d'Erreurs ---
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    logging.error(f"Erreur Serveur 500: {e}")
    return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(debug=False)
