from flask import Flask, render_template, request, redirect, url_for
import logging
import os
import json
import requests
from typing import Dict, Any, Optional, List

# --- Initialisation de Flask ---
app = Flask(__name__)

# --- Configuration ---
# Assurez-vous que ces variables sont bien configurées sur Render !
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

# --- Filtres Jinja2 pour le Template ---
@app.template_filter()
def format_pnl(value: float) -> str:
    try:
        value = float(value)
        sign = "+" if value > 0 else ""
        return f"{sign}${value:,.2f}"
    except (ValueError, TypeError):
        return "N/A"

# --- Services ---
class BirdeyeService:
    BASE_URL_V1 = "https://public-api.birdeye.so"
    HEADERS = {
        "X-API-KEY": app.config['BIRDEYE_API_KEY'],
        "x-chain": "solana"
    }

    @staticmethod
    def get_wallet_transactions(wallet_address: str) -> tuple[List[Dict[str, Any]], Optional[str]]:
        url = f"{BirdeyeService.BASE_URL_V1}/defi/tx_list?address={wallet_address}&tx_type=all&limit=25&offset=0"
        try:
            response = requests.get(url, headers=BirdeyeService.HEADERS)
            response.raise_for_status()
            data = response.json()
            return (data.get('data', {}).get('items', []), None) if data.get('success') else ([], "Réponse invalide de l'API")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_wallet_transactions): {e}")
            return [], str(e)

    @staticmethod
    def get_gainers_losers() -> tuple[Dict[str, Any], Optional[str]]:
        url = f"{BirdeyeService.BASE_URL_V1}/defi/gainers-losers?sort_by=gain_percent&sort_type=desc&limit=10"
        try:
            response = requests.get(url, headers=BirdeyeService.HEADERS)
            response.raise_for_status()
            data = response.json()
            return (data.get('data', {}), None) if data.get('success') else ({}, "Réponse invalide de l'API")
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
            return (data.get('data', {}).get('tokens', []), None) if data.get('success') else ([], "Réponse invalide de l'API")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_trending_tokens): {e}")
            return [], str(e)

class AIService:
    @staticmethod
    def analyze_wallet(transactions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not model:
            logging.error("Modèle IA non disponible pour l'analyse.")
            return None
        
        # Simplifier les données pour le prompt
        simplified_txs = json.dumps([{
            "type": tx.get("txType"),
            "token": tx.get("symbol"),
            "amount_usd": tx.get("amountUsd")
        } for tx in transactions])

        prompt = f"""
        Analyse la liste des 25 dernières transactions d'un wallet Solana : {simplified_txs}.
        En te basant sur ces données limitées, agis comme un analyste crypto expert.

        Calcule ou estime les métriques suivantes :
        1.  "winrate": Le pourcentage de trades qui semblent profitables (considère un "swap" suivi d'un autre "swap" du même token comme un trade). Sois conservateur.
        2.  "pnl_usd": Une estimation très approximative du Profit & Loss en USD sur ces trades.
        3.  "top_tokens": Une liste des 3 tokens les plus fréquemment échangés.
        4.  "behavior": Une brève description du comportement du trader (ex: "Scalper", "Swing Trader", "Degen").
        5.  "copy_verdict": Un verdict clair sur la pertinence de copier ce trader, parmi : "Très Recommandé", "Potentiellement Rentable", "Prudence Requise", "Non Recommandé".
        6.  "summary": Un résumé d'une phrase expliquant ton verdict.

        Retourne ta réponse UNIQUEMENT en format JSON valide, sans texte additionnel ni markdown.
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
    return render_template("tendances.html", trending_data=trending_data, error=error)

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

# --- Gestionnaires d'Erreurs ---
@app.errorhandler(404)
def not_found(e): return "<h1>Page non trouvée</h1>", 404
@app.errorhandler(500)
def server_error(e): logging.error(f"Erreur Serveur 500: {e}"); return "<h1>Erreur interne du serveur</h1>", 500

if __name__ == "__main__":
    app.run(debug=True)
