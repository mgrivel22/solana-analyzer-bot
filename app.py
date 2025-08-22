from flask import Flask, render_template, request, jsonify
import requests
import logging
import time
import os
import json
import google.generativeai as genai

app = Flask(__name__)

# --- Configuration des API ---
try:
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    MORALIS_API_KEY = os.environ.get('MORALIS_API_KEY') # Nouvelle clé
    if not GEMINI_API_KEY: print("ATTENTION: Clé API Gemini non trouvée.")
    if not MORALIS_API_KEY: print("ATTENTION: Clé API Moralis non trouvée.")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    print(f"Erreur de configuration: {e}"); model = None

# ... (Les autres fonctions comme le formatage, RugCheck, analyse IA, etc., ne changent pas)
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
# ... (le reste de l'app.py reste identique à la version 'finale' précédente)

# --- Routes des pages ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/tendances")
def tendances():
    if not MORALIS_API_KEY:
        return render_template("tendances.html", error="La clé API Moralis n'est pas configurée sur le serveur.")
    
    trending_data = None
    error = None
    
    try:
        url = "https://solana-gateway.moralis-streams.com/api/v2/market-data/spl/top-movers"
        headers = {
            "accept": "application/json",
            "X-API-Key": MORALIS_API_KEY
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        # On prend les 10 plus grosses hausses (top_gainers)
        trending_data = data.get('top_gainers', [])[:10]

    except Exception as e:
        logger.error(f"Erreur lors de la récupération des tendances Moralis: {e}")
        error = "Impossible de charger les données des tendances depuis Moralis."
        
    return render_template("tendances.html", trending_data=trending_data, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    # ... (cette route ne change pas)
    return render_template("results.html", results=[])

# Le reste de votre app.py (get_final_analysis, etc.) reste ici...
# Assurez-vous que le reste du fichier app.py est bien celui de la version finale précédente.
# Seule la route /tendances a besoin d'être remplacée.