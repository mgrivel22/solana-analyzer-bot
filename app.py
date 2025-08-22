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
    # Lit les clés depuis les variables d'environnement de Render
    GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
    BIRDEYE_API_KEY = os.environ['BIRDEYE_API_KEY']
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("INFO: Clés API Gemini et Birdeye chargées avec succès.")

except KeyError as e:
    print(f"ERREUR CRITIQUE: La variable d'environnement {e} est MANQUANTE sur Render !")
    model = None
    BIRDEYE_API_KEY = None # Assure que les fonctions qui en dépendent échoueront proprement

# --- Fonctions de formatage pour l'affichage ---
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
def get_birdeye_overview(token_address):
    if not BIRDEYE_API_KEY: return None
    try:
        url = f"https://public-api.birdeye.so/defi/token_overview?address={token_address}"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data.get('data') if data.get('success') else None
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API Birdeye Overview: {e}"); return None

def get_rugcheck_data(token_address):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
        response = requests.get(url, timeout=15)
        return response.json() if response.ok else None
    except Exception as e:
        logger.error(f"Erreur API RugCheck: {e}"); return None

def get_final_analysis_and_score(dex_data, token_address):
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
    volume = dex_data.get('v24hUSD', 0)
    txns = dex_data.get('txns24h', 0)
    act_score = 0
    if volume > 50000: act_score += 15
    if txns > 500: act_score += 15
    scores['activity'] = act_score

    # 3. Tendance
    price_change = dex_data.get('priceChange24hPercent', 0)
    if price_change is not None and price_change > 0:
        scores['trend'] = 10
    
    # 4. Appel IA
    ai_data = {"final_verdict": "Indisponible", "probability": 0, "summary": "L'analyse IA n'a pas pu être effectuée."}
    if model:
        prompt = f"""Analyse les données suivantes pour le token "{dex_data.get('name')}" (${dex_data.get('symbol')}):
        - Market Cap: ${dex_data.get('mc', 0):,.0f}
        - Volume 24h: ${volume:,.0f}
        - Transactions 24h: {txns}
        - Variation prix 24h: {price_change}%
        - Score de sécurité (sur 40): {scores['security']}
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
    if not BIRDEYE_API_KEY:
        return render_template("tendances.html", error="La clé API Birdeye n'est pas configurée sur le serveur.")
    
    trending_data, error, market_stats, market_health = [], None, {}, {"status": "Indisponible", "color": "gray"}
    
    try:
        url = "https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hUSD&sort_type=desc"
        headers = {"X-API-KEY": BIRDEYE_API_KEY}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if data.get('success'):
            all_tokens = data.get('data', {}).get('tokens', [])
            solana_tokens = [t for t in all_tokens if t.get('chainId') == 'solana'][:15]
            trending_data = solana_tokens
            
            if solana_tokens:
                total_volume = sum(t.get('v24hUSD', 0) for t in solana_tokens)
                price_changes = [t.get('priceChange24hPercent', 0) for t in solana_tokens if t.get('priceChange24hPercent') is not None]
                avg_change = sum(price_changes) / len(price_changes) if price_changes else 0
                
                if avg_change > 100: market_health = {"status": "🔥 Marché en Feu", "color": "#28a745"}
                elif avg_change > 20: market_health = {"status": "🟢 Marché Haussier", "color": "#8BC34A"}
                elif avg_change < -20: market_health = {"status": "🔴 Marché Baissier", "color": "#dc3545"}
                else: market_health = {"status": "🟡 Marché Neutre", "color": "#ffc107"}
                
                market_stats = {"volume": total_volume, "avg_change": avg_change}
        else:
            error = "La réponse de Birdeye est invalide."

    except Exception as e:
        logger.error(f"Erreur récupération tendances Birdeye: {e}")
        error = "Impossible de charger les données des tendances."
        
    return render_template("tendances.html", trending_data=trending_data, market_stats=market_stats, market_health=market_health, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    token_address = request.form["token"].strip()
    results = []
    
    dex_data = get_birdeye_overview(token_address)
    
    if not dex_data:
        results.append({"token": token_address, "error": "Token non trouvé via Birdeye. Vérifiez l'adresse."})
    else:
        total_score, score_details, ai_data = get_final_analysis_and_score(dex_data, token_address)
        
        pair_address = next((p['address'] for p in dex_data.get('pairs', []) if 'raydium' in p.get('source', '').lower()), None)
        if not pair_address and dex_data.get('pairs'):
            pair_address = dex_data['pairs'][0]['address']
        
        results.append({
            "token": token_address, "token_name": dex_data.get("name"), "token_symbol": dex_data.get("symbol"),
            "current_price": dex_data.get("price"), "market_cap": dex_data.get("mc"),
            "total_score": total_score, "score_details": score_details, "ai_analysis": ai_data,
            "pair_address": pair_address
        })
    return render_template("results.html", results=results)

if __name__ == "__main__":
    app.run(debug=True)