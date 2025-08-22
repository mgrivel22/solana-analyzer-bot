from flask import Flask, render_template, request
import logging
import os
import json
import requests
from typing import Dict, Any, Optional, List

# --- Initialisation de Flask ---
app = Flask(__name__)

# --- Configuration ---
app.config['BIRDEYE_API_KEY'] = os.environ.get('BIRDEYE_API_KEY')
app.config['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY')

# --- Initialisation de l'API Gemini ---
model = None
if app.config['GEMINI_API_KEY']:
    try:
        import google.generativeai as genai
        genai.configure(api_key=app.config['GEMINI_API_KEY'])
        model = genai.GenerativeModel('gemini-1.5-flash')
        logging.info("INFO: API Gemini configurée avec succès")
    except Exception as e:
        logging.error(f"ERREUR: La configuration de l'API Gemini a échoué - {e}")

# --- Configuration du Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Filtres Jinja2 ---
@app.template_filter()
def format_number(value):
    try:
        value = float(value)
        if value >= 1_000_000_000: return f"{value/1_000_000_000:.2f}B"
        if value >= 1_000_000: return f"{value/1_000_000:.2f}M"
        if value >= 1_000: return f"{value/1_000:.2f}K"
        return f"{value:,.2f}"
    except (ValueError, TypeError): return "N/A"

# --- Services ---
class DexScreenerService:
    @staticmethod
    def get_token_data(token_address: str) -> Optional[Dict[str, Any]]:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            # On choisit la pair avec le plus de liquidité en USD
            if data and data.get('pairs'):
                main_pair = max(data['pairs'], key=lambda p: p.get('liquidity', {}).get('usd', 0))
                return main_pair
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API DexScreener: {e}")
            return None

class BirdeyeService:
    @staticmethod
    def get_trending_tokens() -> tuple[List[Dict[str, Any]], Optional[str]]:
        url = f"https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hUSD&sort_type=desc&limit=50"
        headers = {"X-API-KEY": app.config['BIRDEYE_API_KEY']}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return (data.get('data', {}).get('tokens', []), None) if data.get('success') else ([], "Réponse invalide")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_trending_tokens): {e}")
            return [], str(e)

class AIService:
    @staticmethod
    def analyze_token(token_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not model:
            return {"error": "Le service IA n'est pas configuré."}
        
        # Préparation des données pour le prompt
        data_for_prompt = {
            "nom": token_data.get('baseToken', {}).get('name'),
            "symbole": token_data.get('baseToken', {}).get('symbol'),
            "prix_usd": token_data.get('priceUsd'),
            "variation_24h_pourcent": token_data.get('priceChange', {}).get('h24'),
            "volume_24h_usd": token_data.get('volume', {}).get('h24'),
            "liquidite_usd": token_data.get('liquidity', {}).get('usd'),
            "market_cap": token_data.get('fdv'), # Fully Diluted Valuation (Market Cap)
            "transactions_24h": token_data.get('txns', {}).get('h24', {}).get('buys', 0) + token_data.get('txns', {}).get('h24', {}).get('sells', 0)
        }

        prompt = f"""
        Analyse ce token Solana avec les données de DexScreener : {json.dumps(data_for_prompt)}.
        Agis comme un analyste crypto expert et concis.

        Fournis une analyse structurée.
        1.  "verdict": Un verdict d'investissement unique et direct parmi : "STRONG BUY", "BUY", "HOLD", "SELL", "HIGH-RISK".
        2.  "risk_score": Un score de risque de 1 (très faible) à 10 (très élevé).
        3.  "positive_points": Une liste de 2 à 3 points positifs clés (en français).
        4.  "negative_points": Une liste de 2 à 3 points négatifs ou risques (en français).
        5.  "summary": Un résumé final d'une phrase expliquant ta recommandation.

        Retourne ta réponse UNIQUEMENT en format JSON valide.
        """
        try:
            response = model.generate_content(prompt)
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(cleaned_response)
        except Exception as e:
            logging.error(f"Erreur analyse Gemini: {e}")
            return {"error": "L'analyse par l'IA a échoué.", "summary": str(e)}

# --- Routes Flask ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyzer", methods=["GET", "POST"])
def analyzer():
    if request.method == "POST":
        token_address = request.form.get("token", "").strip()
        if not token_address:
            return render_template("analyzer.html", error="L'adresse du token est requise.")
        
        token_data = DexScreenerService.get_token_data(token_address)
        if not token_data:
            return render_template("analyzer.html", error="Token non trouvé sur DexScreener ou erreur API.")

        ai_analysis = AIService.analyze_token(token_data)
        
        return render_template("analyzer_results.html", 
                               analysis=ai_analysis, 
                               token=token_data)
    
    return render_template("analyzer.html")

@app.route("/tendances")
def tendances():
    trending_data, error = BirdeyeService.get_trending_tokens()
    return render_template("tendances.html", trending_data=trending_data, error=error)

# --- Gestionnaires d'Erreurs ---
@app.errorhandler(404)
def not_found(e): return render_template("404.html"), 404
@app.errorhandler(500)
def server_error(e): logging.error(f"Erreur Serveur 500: {e}"); return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(debug=True)
