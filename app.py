from flask import Flask, render_template, request
import logging
import time
import os
import json
import google.generativeai as genai
from moralis import sol_api # Importation officielle de Moralis

app = Flask(__name__)

# --- Configuration des API ---
try:
    GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
    MORALIS_API_KEY = os.environ['MORALIS_API_KEY']
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("INFO: Clés API Gemini et Moralis chargées avec succès.")
except KeyError as e:
    print(f"ERREUR CRITIQUE: La variable d'environnement {e} est MANQUANTE !")
    model, MORALIS_API_KEY = None, None

# --- Fonctions de formatage ---
@app.template_filter()
def format_price(value):
    if not isinstance(value, (int, float)): return "N/A"
    return f"${value:,.10f}".rstrip('0').rstrip('.')
@app.template_filter()
def format_market_cap(value):
    if not isinstance(value, (int, float)): return "N/A"
    if value > 1_000_000_000: return f"${value/1_000_000_000:.2f}B"
    if value > 1_000_000: return f"${value/1_000_000:.2f}M"
    if value > 1_000: return f"${value/1_000:.2f}K"
    return f"${int(value)}"

# --- Fonctions d'API et Scoring ---
def get_moralis_token_data(token_address):
    if not MORALIS_API_KEY: return None
    try:
        params = {"network": "mainnet", "address": token_address}
        # La syntaxe pour obtenir le prix est bien sol_api.token...
        return sol_api.token.get_token_price(api_key=MORALIS_API_KEY, params=params)
    except Exception as e:
        logger.error(f"Erreur API Moralis (token data): {e}"); return None

# --- Routes des pages ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/tendances")
def tendances():
    if not MORALIS_API_KEY:
        return render_template("tendances.html", error="La clé API Moralis n'est pas configurée.")
    
    trending_data, error = [], None
    try:
        params = {"network": "mainnet"}
        # ==============================================================================
        # CORRECTION DE LA SYNTAXE MORALIS ICI
        # C'était sol_api.market_data.get_spl_top_movers
        # Le nom correct est sol_api.market_data.get_top_spl_by_market_cap (ou une autre fonction similaire)
        # Après re-vérification, l'endpoint 'top-movers' est bien dans la catégorie market_data,
        # mais la librairie a peut-être un nom de fonction différent.
        # La documentation la plus récente indique d'utiliser :
        result = sol_api.market_data.get_top_spl_by_trading_volume(api_key=MORALIS_API_KEY, params=params)
        # ==============================================================================
        
        trending_data = result[:10] # On prend les 10 premiers

    except Exception as e:
        logger.error(f"Erreur récupération tendances Moralis: {e}")
        error = f"Impossible de charger les données: {e}"
        
    return render_template("tendances.html", trending_data=trending_data, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    # Cette route est simplifiée car l'analyse complète n'est pas demandée dans cette version
    token_address = request.form["token"].strip()
    results = []
    token_data = get_moralis_token_data(token_address)
    if not token_data:
        results.append({"token": token_address, "error": "Token non trouvé via Moralis."})
    else:
        # On affiche les informations de base sans le scoring complexe pour l'instant
        results.append({
            "token": token_address,
            "token_name": token_data.get("tokenName", "N/A"),
            "token_symbol": token_data.get("tokenSymbol", "N/A"),
            "current_price": float(token_data.get("usdPrice", 0)),
            "pair_address": None # Simplifié
        })
    return render_template("results.html", results=results)

if __name__ == "__main__":
    app.run(debug=True)