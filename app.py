from flask import Flask, render_template, request
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
    MORALIS_API_KEY = os.environ['MORALIS_API_KEY'] # On utilise bien la clé Moralis
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("INFO: Clés API Gemini et Moralis chargées avec succès.")
except KeyError as e:
    print(f"ERREUR CRITIQUE: La variable d'environnement {e} est MANQUANTE sur Render !")
    model = None
    MORALIS_API_KEY = None

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
# NOTE: La fonction pour Birdeye a été supprimée, on utilise maintenant Dexscreener pour l'analyse individuelle
# car leur API est plus simple pour un token unique et évite d'utiliser notre clé Moralis pour chaque analyse.
def get_dexscreener_data(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={token_address}"
        # On utilise scraper de cloudscraper pour éviter les blocages
        scraper = requests # Fallback simple, cloudscraper n'est plus une dépendance requise
        response = scraper.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data["pairs"][0] if data.get("pairs") else None
    except Exception as e:
        logger.error(f"Erreur API DexScreener: {e}"); return None

def get_rugcheck_data(token_address):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
        response = requests.get(url, timeout=15)
        return response.json() if response.ok else None
    except Exception as e:
        logger.error(f"Erreur API RugCheck: {e}"); return None

def get_final_analysis_and_score(dex_data, token_address):
    scores = {"security": 0, "activity": 0, "hype": 0, "trend": 0}
    rugcheck_data = get_rugcheck_data(token_address)
    if rugcheck_data and rugcheck_data.get('risks'):
        sec_score = 40
        for risk in rugcheck_data['risks']:
            if risk['name'] in ['Mutable Metadata', 'Mint Authority Enabled', 'High Concentration of Holders']: sec_score -= 15
        scores['security'] = max(0, sec_score)
    
    volume = dex_data.get('volume', {}).get('h24', 0)
    txns = dex_data.get('txns', {}).get('h24', {})
    act_score = 0
    if volume > 50000: act_score += 15
    if txns.get('buys', 0) > txns.get('sells', 0): act_score += 15
    scores['activity'] = act_score

    price_change = dex_data.get('priceChange', {}).get('h24', 0)
    if price_change is not None and price_change > 0: scores['trend'] = 10
    
    ai_data = {"final_verdict": "Indisponible", "probability": 0, "summary": "L'analyse IA n'a pas pu être effectuée."}
    if model:
        prompt = f"""Analyse les données pour le token "{dex_data.get('baseToken',{}).get('name')}" (${dex_data.get('baseToken',{}).get('symbol')}):
        - Market Cap: ${dex_data.get('fdv', 0):,.0f} - Volume 24h: ${volume:,.0f}
        - Variation prix 24h: {price_change}% - Score de sécurité (sur 40): {scores['security']}
        Réponds UNIQUEMENT en JSON: {{"hype_score": <0-100>, "final_verdict": "BUY NOW, POTENTIAL BUY, WAIT ou HIGH RISK", "probability": <0-100>, "summary": "<1 phrase>"}}"""
        try:
            response = model.generate_content(prompt)
            cleaned_text = response.text.strip().replace("```json", "").replace("```", "")
            ai_data = json.loads(cleaned_text)
            scores['hype'] = round(ai_data.get('hype_score', 0) * 0.20)
        except Exception as e:
            logger.error(f"Erreur API Gemini: {e}")
    
    total_score = sum(scores.values())
    return total_score, scores, ai_data

# --- Routes des pages ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/tendances")
def tendances():
    if not MORALIS_API_KEY:
        return render_template("tendances.html", error="La clé API Moralis n'est pas configurée sur le serveur.")
    
    trending_data, error, market_stats, market_health = [], None, {}, {"status": "Indisponible", "color": "gray"}
    try:
        url = "https://solana-gateway.moralis.io/api/v2/market-data/spl/top-movers"
        headers = {"accept": "application/json", "X-API-Key": MORALIS_API_KEY}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        trending_data = data.get('top_gainers', [])[:10]
        
        if trending_data:
            price_changes = [float(t.get('price_change_24h_percent', 0)) for t in trending_data if t.get('price_change_24h_percent') is not None]
            avg_change = sum(price_changes) / len(price_changes) if price_changes else 0
            if avg_change > 50: market_health = {"status": "🔥 Marché en Feu", "color": "#28a745"}
            elif avg_change > 10: market_health = {"status": "🟢 Marché Haussier", "color": "#8BC34A"}
            else: market_health = {"status": "🟡 Marché Neutre", "color": "#ffc107"}
    except Exception as e:
        logger.error(f"Erreur récupération tendances Moralis: {e}")
        error = "Impossible de charger les données des tendances."
    return render_template("tendances.html", trending_data=trending_data, market_health=market_health, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    token_address = request.form["token"].strip()
    results = []
    dex_data = get_dexscreener_data(token_address)
    if not dex_data:
        results.append({"token": token_address, "error": "Token non trouvé. Vérifiez l'adresse."})
    else:
        total_score, score_details, ai_data = get_final_analysis_and_score(dex_data, token_address)
        results.append({
            "token": token_address, "token_name": dex_data.get("baseToken",{}).get("name"), 
            "token_symbol": dex_data.get("baseToken",{}).get("symbol"),
            "current_price": float(dex_data.get("priceUsd", 0)), "market_cap": float(dex_data.get("fdv", 0)),
            "pair_address": dex_data.get("pairAddress"), "total_score": total_score, 
            "score_details": score_details, "ai_analysis": ai_data
        })
    return render_template("results.html", results=results)

if __name__ == "__main__":
    app.run(debug=True)