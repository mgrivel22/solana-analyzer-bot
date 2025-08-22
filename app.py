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
    # On lit les clés. Si elles manquent, une erreur claire sera affichée dans les logs.
    GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
    BIRDEYE_API_KEY = os.environ['BIRDEYE_API_KEY'] 
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("INFO: Clés API Gemini et Birdeye chargées avec succès.")
except KeyError as e:
    print(f"ERREUR CRITIQUE: La variable d'environnement {e} est manquante sur Render !")
    model = None
    BIRDEYE_API_KEY = None
except Exception as e:
    print(f"Erreur IA Config: {e}"); model = None

# ... (les fonctions de formatage et de scoring ne changent pas) ...
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

def get_rugcheck_data(token_address):
    # ...
    return None
@app.route('/api/get_final_analysis', methods=['POST'])
def get_final_analysis():
    # ...
    return jsonify({})

# --- Routes des pages ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/tendances")
def tendances():
    if not BIRDEYE_API_KEY:
        return render_template("tendances.html", error="La clé API Birdeye n'est pas configurée sur le serveur.")
        
    trending_data = None
    error = None
    market_stats = {}
    market_health = {"status": "Indisponible", "color": "gray"}
    
    try:
        # NOUVELLE URL CORRIGÉE POUR LES TENDANCES
        url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hUSD&sort_type=desc"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get('success'):
            # On filtre pour ne garder que les tokens Solana
            all_tokens = data.get('data', {}).get('tokens', [])
            solana_tokens = [t for t in all_tokens if t.get('chainId') == 'solana'][:15] # On garde les 15 premiers
            trending_data = solana_tokens
            
            # Calcul des stats du marché
            total_volume = sum(t.get('v24hUSD', 0) for t in solana_tokens)
            price_changes = [t.get('priceChange24hPercent', 0) for t in solana_tokens if t.get('priceChange24hPercent') is not None]
            avg_change = sum(price_changes) / len(price_changes) if price_changes else 0
            
            if avg_change > 100: market_health = {"status": "🔥 Marché en Feu", "color": "#28a745"}
            elif avg_change > 20: market_health = {"status": "🟢 Marché Haussier", "color": "#8BC34A"}
            elif avg_change < -20: market_health = {"status": "🔴 Marché Baissier", "color": "#dc3545"}
            else: market_health = {"status": "🟡 Marché Neutre", "color": "#ffc107"}
            
            market_stats = {"volume": total_volume, "avg_change": avg_change}

    except Exception as e:
        logger.error(f"Erreur récupération tendances Birdeye: {e}")
        error = "Impossible de charger les données des tendances (l'API a peut-être changé)."
        
    return render_template("tendances.html", trending_data=trending_data, market_stats=market_stats, market_health=market_health, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    # ... (le reste du code est inchangé)
    return render_template("results.html", results=[])

if __name__ == "__main__": app.run(debug=True)