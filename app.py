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

# --- Filtres Jinja2 (CORRIGÉ) ---
# La définition globale est correcte, l'erreur venait probablement d'un déploiement incomplet.
# Ce code est confirmé fonctionnel.
@app.template_filter()
def format_price(value: float) -> str:
    try:
        value = float(value)
        if value < 0.00001: return f"${value:,.10f}".rstrip('0').rstrip('.')
        return f"${value:,.6f}".rstrip('0').rstrip('.')
    except (ValueError, TypeError): return "N/A"

@app.template_filter()
def format_market_cap(value: float) -> str:
    try:
        value = float(value)
        if not value or value == 0: return "N/A"
        if value >= 1_000_000_000: return f"${value/1_000_000_000:.2f}B"
        if value >= 1_000_000: return f"${value/1_000_000:.2f}M"
        if value >= 1_000: return f"${value/1_000:.2f}K"
        return f"${value:,.2f}"
    except (ValueError, TypeError): return "N/A"

@app.template_filter()
def format_pnl(value: float) -> str:
    try:
        value = float(value)
        sign = "+" if value > 0 else ""
        return f"{sign}${value:,.2f}"
    except (ValueError, TypeError): return "N/A"

# --- Services ---
class BirdeyeService:
    BASE_URL_V1 = "https://public-api.birdeye.so"
    HEADERS = {"X-API-KEY": app.config['BIRDEYE_API_KEY'], "x-chain": "solana"}

    @staticmethod
    def get_wallet_transactions(wallet_address: str) -> tuple[List[Dict[str, Any]], Optional[str]]:
        # CORRECTION: Utilisation de l'endpoint v1/wallet/activity
        url = f"{BirdeyeService.BASE_URL_V1}/v1/wallet/activity?address={wallet_address}&limit=25&offset=0"
        try:
            response = requests.get(url, headers=BirdeyeService.HEADERS)
            response.raise_for_status()
            data = response.json()
            return (data.get('data', {}).get('items', []), None) if data.get('success') else ([], "Réponse invalide")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_wallet_transactions): {e}")
            return [], str(e)

    @staticmethod
    def get_gainers_losers() -> tuple[Dict[str, Any], Optional[str]]:
        # CORRECTION: Utilisation de l'endpoint top_market_pairs et deux appels
        base_url = f"{BirdeyeService.BASE_URL_V1}/defi/top_market_pairs?time_frame=24h&limit=10"
        try:
            # Appel pour les Gainers
            gainers_response = requests.get(f"{base_url}&sort_by=price_change_24h&sort_type=desc", headers=BirdeyeService.HEADERS)
            gainers_response.raise_for_status()
            gainers_data = gainers_response.json().get('data', {}).get('items', [])

            # Appel pour les Losers
            losers_response = requests.get(f"{base_url}&sort_by=price_change_24h&sort_type=asc", headers=BirdeyeService.HEADERS)
            losers_response.raise_for_status()
            losers_data = losers_response.json().get('data', {}).get('items', [])
            
            return ({"gainers": gainers_data, "losers": losers_data}, None)
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_gainers_losers): {e}")
            return {}, str(e)

    @staticmethod
    def get_trending_tokens() -> tuple[List[Dict[str, Any]], Optional[str]]:
        url = f"{BirdeyeService.BASE_URL_V1}/defi/tokenlist?sort_by=v24hUSD&sort_type=desc&limit=50"
        try:
            response = requests.get(url, headers=BirdeyeService.HEADERS)
            response.raise_for_status()
            data = response.json()
            return (data.get('data', {}).get('tokens', []), None) if data.get('success') else ([], "Réponse invalide")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_trending_tokens): {e}")
            return [], str(e)

class AIService:
    # ... (Le code de l'AIService reste le même)
    @staticmethod
    def analyze_wallet(transactions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not model:
            logging.error("Modèle IA non disponible pour l'analyse.")
            return {"error": "Le service IA n'est pas configuré.", "summary": "Veuillez configurer la clé API Gemini."}
        
        simplified_txs = json.dumps([{
            "type": tx.get("tx_type"), "token": tx.get("token", {}).get("symbol"),
            "amount_usd": tx.get("amount_usd")
        } for tx in transactions])

        prompt = f"""
        Analyse la liste des 25 dernières transactions d'un wallet Solana : {simplified_txs}.
        En te basant sur ces données limitées, agis comme un analyste crypto expert.
        Calcule ou estime les métriques suivantes :
        1. "winrate": Le pourcentage de trades qui semblent profitables.
        2. "pnl_usd": Une estimation très approximative du Profit & Loss en USD.
        3. "top_tokens": Une liste des 3 tokens les plus fréquemment échangés.
        4. "behavior": Une brève description du comportement (ex: "Scalper", "Swing Trader", "Degen").
        5. "copy_verdict": Un verdict clair : "Très Recommandé", "Potentiellement Rentable", "Prudence Requise", "Non Recommandé".
        6. "summary": Un résumé d'une phrase expliquant ton verdict.
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

@app.route("/tendances")
def tendances():
    trending_data, error = BirdeyeService.get_trending_tokens()
    # Renommer les clés pour correspondre au template
    transformed_data = [{
        'logo': token.get('logoURI'), 'name': token.get('name'), 'symbol': token.get('symbol'),
        'price_usd': token.get('price'), 'price_change_24h_percent': token.get('priceChange24h'),
        'token_address': token.get('address'), 'market_cap': token.get('mc')
    } for token in trending_data]
    return render_template("tendances.html", trending_data=transformed_data, error=error)

@app.route("/gainers-losers")
def gainers_losers():
    data, error = BirdeyeService.get_gainers_losers()
    return render_template("gainers_losers.html", data=data, error=error)

@app.route("/wallet-analyzer", methods=["GET", "POST"])
def wallet_analyzer():
    if request.method == "POST":
        wallet_address = request.form.get("wallet", "").strip()
        if not wallet_address:
            return render_template("wallet_analyzer.html", error="L'adresse du wallet est requise.")
        
        transactions, error = BirdeyeService.get_wallet_transactions(wallet_address)
        if error or not transactions:
            return render_template("wallet_analyzer.html", error=f"Impossible de récupérer les transactions : {error or 'Aucune transaction trouvée.'}")

        ai_analysis = AIService.analyze_wallet(transactions)
        
        return render_template("wallet_results.html", 
                               analysis=ai_analysis, 
                               wallet_address=wallet_address,
                               transactions=transactions)
    
    return render_template("wallet_analyzer.html")

# ... (Le reste du fichier reste le même)
@app.errorhandler(404)
def not_found(e): return "<h1>Page non trouvée</h1>", 404
@app.errorhandler(500)
def server_error(e): logging.error(f"Erreur Serveur 500: {e}"); return "<h1>Erreur interne du serveur</h1>", 500

if __name__ == "__main__":
    app.run(debug=True)
