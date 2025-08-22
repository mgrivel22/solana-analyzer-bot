from flask import Flask, render_template, request, jsonify
import requests
import cloudscraper
import logging
import time
import os
import json
import google.generativeai as genai

app = Flask(__name__)
scraper = cloudscraper.create_scraper()

# --- Configuration des API ---
try:
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    BIRDEYE_API_KEY = os.environ.get('BIRDEYE_API_KEY')
    if not GEMINI_API_KEY: print("ATTENTION: Clé API Gemini non trouvée.")
    if not BIRDEYE_API_KEY: print("ATTENTION: Clé API Birdeye non trouvée.")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    print(f"Erreur IA Config: {e}"); model = None

# --- Fonctions de formatage ---
@app.template_filter()
def format_price(value):
    if not isinstance(value, (int, float)): return "N/A"
    return f"${Number(value).toLocaleString('en-US',{minimumFractionDigits:2, maximumFractionDigits:10})}"

@app.template_filter()
def format_market_cap(value):
    if not isinstance(value, (int, float)): return "N/A"
    if value > 1e9: return f"${(value / 1e9).toFixed(2)}B"
    if value > 1e6: return f"${(value / 1e6).toFixed(2)}M"
    if value > 1e3: return f"${(value / 1e3).toFixed(2)}K"
    return f"${Math.round(value)}"

# --- Fonctions d'API ---
def get_birdeye_overview(token_address):
    if not BIRDEYE_API_KEY: return None
    try:
        url = f"https://public-api.birdeye.so/defi/token_overview?address={token_address}"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get('data') if data.get('success') else None
    except Exception as e:
        logger.error(f"Erreur API Birdeye Overview: {e}"); return None

def get_rugcheck_data(token_address):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
        response = requests.get(url, timeout=15)
        return response.json() if response.ok else None
    except Exception as e:
        logger.error(f"Erreur API RugCheck: {e}"); return None

# --- L'IA et l'Algorithme de Scoring ---
def get_final_analysis(dex_data, token_address):
    # Cette fonction interne fait le scoring + l'appel IA
    scores = {"security": 0, "activity": 0, "hype": 0, "trend": 0}
    
    # 1. Sécurité
    rugcheck_data = get_rugcheck_data(token_address)
    if rugcheck_data and rugcheck_data.get('risks'):
        sec_score = 40
        for risk in rugcheck_data['risks']:
            if risk['name'] in ['Mutable Metadata', 'Mint Authority Enabled', 'High Concentration of Holders']:
                sec_score -= 15
        scores['security'] = max(0, sec_score)
    
    # 2. Volume / Activité
    volume = dex_data.get('volume', {})
    txns = dex_data.get('txns', {}).get('h1', {})
    act_score = 0
    if volume.get('h6', 0) > 0 and volume.get('h1', 0) > (volume.get('h6', 0) / 6): act_score += 15
    if txns.get('buys', 0) > txns.get('sells', 0): act_score += 15
    scores['activity'] = act_score

    # 3. Tendance
    price_change = dex_data.get('priceChange', {})
    if price_change.get('h6', 0) > 0 and price_change.get('m5', 0) > -20:
        scores['trend'] = 10
    
    # 4. Appel IA pour le Hype et le verdict final
    prompt = f"..." # Le prompt reste le même
    ai_data = {}
    try:
        if not model: raise ValueError("Modèle IA non initialisé")
        response = model.generate_content(prompt)
        ai_data = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
        scores['hype'] = round(ai_data.get('hype_score', 0) * 0.20)
    except Exception as e:
        logger.error(f"Erreur finale API Gemini: {e}")
        ai_data = {"final_verdict": "Erreur IA", "probability": 0, "summary": "L'analyse IA a échoué."}
    
    total_score = sum(scores.values())
    return total_score, scores, ai_data


# --- Routes des pages ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/tendances")
def tendances():
    if not BIRDEYE_API_KEY:
        return render_template("tendances.html", error="La clé API Birdeye n'est pas configurée.")
        
    try:
        url = "https://public-api.birdeye.so/defi/hot_pairs?sort_by=txs_30m&sort_type=desc&chain=solana"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        trending_data = data.get('data', {}).get('pairs', [])[:15] if data.get('success') else []
        
        # Calcul des stats du marché
        total_volume = sum(pair.get('volume', {}).get('h24', 0) for pair in trending_data)
        price_changes = [pair.get('priceChange', {}).get('h24', 0) for pair in trending_data]
        avg_change = sum(price_changes) / len(price_changes) if price_changes else 0

        if avg_change > 50: market_health = {"status": "🔥 Marché en Feu", "color": "#28a745"}
        elif avg_change > 10: market_health = {"status": "🟢 Marché Haussier", "color": "#8BC34A"}
        elif avg_change < -20: market_health = {"status": "🔴 Marché Baissier", "color": "#dc3545"}
        else: market_health = {"status": "🟡 Marché Neutre", "color": "#ffc107"}
        
        market_stats = {"volume": total_volume, "avg_change": avg_change}

    except Exception as e:
        logger.error(f"Erreur récupération tendances Birdeye: {e}")
        trending_data, market_stats, market_health = [], {}, {"status": "Erreur", "color": "gray"}
        
    return render_template("tendances.html", trending_data=trending_data, market_stats=market_stats, market_health=market_health)

@app.route("/analyze", methods=["POST"])
def analyze():
    token_address = request.form["token"].strip()
    results = []
    
    # L'analyse se fait maintenant entièrement sur le serveur
    dex_data = get_birdeye_overview(token_address)
    
    if not dex_data:
        results.append({"token": token_address, "error": "Token non trouvé via Birdeye."})
    else:
        total_score, score_details, ai_data = get_final_analysis(dex_data, token_address)
        results.append({
            "token": token_address,
            "token_name": dex_data.get("name"),
            "token_symbol": dex_data.get("symbol"),
            "current_price": dex_data.get("price"),
            "market_cap": dex_data.get("mc"),
            "total_score": total_score, 
            "score_details": score_details,
            "ai_analysis": ai_data,
            # On cherche une paire pour le graphique, ex: la première paire Raydium
            "pair_address": next((pair['address'] for pair in dex_data.get('pairs', []) if 'raydium' in pair.get('source', '').lower()), None)
        })

    return render_template("results.html", results=results)

if __name__ == "__main__": app.run(debug=True)