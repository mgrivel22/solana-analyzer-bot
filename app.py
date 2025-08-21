from flask import Flask, render_template, request
import requests
import cloudscraper
import logging
import time
import os
import json
import google.generativeai as genai

app = Flask(__name__)
scraper = cloudscraper.create_scraper()

# --- Configuration de l'API Google AI ---
try:
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    if not GEMINI_API_KEY:
        print("Clé API Gemini non trouvée. L'analyse IA sera désactivée.")
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
except Exception as e:
    print(f"Erreur IA Config: {e}"); model = None

# --- Fonctions de formatage ---
@app.template_filter()
def format_price(value):
    if not isinstance(value, (int, float)): return "N/A"
    if value < 0.000001: return f"${value:.10f}".rstrip('0')
    return f"${value:,.8f}".rstrip('0')
@app.template_filter()
def format_market_cap(value):
    if not isinstance(value, (int, float)): return "N/A"
    if value > 1_000_000_000: return f"${value/1_000_000_000:.2f}B"
    if value > 1_000_000: return f"${value/1_000_000:.2f}M"
    if value > 1_000: return f"${value/1_000:.2f}K"
    return f"${int(value)}"

# --- Fonctions d'API ---
def get_dexscreener_data(token_address):
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={token_address}"
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

def get_ai_hype_score(token_name, token_symbol):
    if not model: return {"score": 0, "reason": "IA non configurée."}
    prompt = f"""
    En tant qu'analyste de tendances memecoin sur Solana, évalue le potentiel de hype du token dont le nom est "{token_name}" et le symbole "${token_symbol}".
    Est-ce que le nom est original, drôle, ou lié à une tendance ou un mème populaire actuel (ex: chats, chiens, politique, célébrités) ?
    Ne te base que sur le nom et le symbole.
    Réponds UNIQUEMENT avec un objet JSON au format suivant:
    {{
        "score": <un score de hype de 0 à 100>,
        "reason": "<une justification très courte de 1 phrase pour ce score>"
    }}
    """
    try:
        response = model.generate_content(prompt)
        json_response = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(json_response)
    except Exception as e:
        logger.error(f"Erreur API Gemini: {e}"); return {"score": 0, "reason": "Erreur d'analyse IA."}

# --- ALGORITHME DE SCORING ---
def calculate_final_score(pair_data, rugcheck_data, ai_hype_data):
    scores = { "security": 0, "activity": 0, "hype": 0, "trend": 0 }
    if rugcheck_data and rugcheck_data.get('risks'):
        sec_score = 40
        for risk in rugcheck_data['risks']:
            if risk['name'] == 'Mutable Metadata': sec_score -= 10
            if risk['name'] == 'Mint Authority Enabled': sec_score -= 20
            if risk['name'] == 'High Concentration of Holders': sec_score -= 10
        scores['security'] = max(0, sec_score)
    volume = pair_data.get('volume', {})
    txns = pair_data.get('txns', {}).get('h1', {})
    act_score = 0
    if volume.get('h1', 0) > volume.get('h6', 0) / 6: act_score += 15
    if txns.get('buys', 0) > txns.get('sells', 0): act_score += 15
    scores['activity'] = act_score
    scores['hype'] = round(ai_hype_data.get('score', 0) * 0.20)
    price_change = pair_data.get('priceChange', {})
    if price_change.get('h6', 0) > 0 and price_change.get('m5', 0) > -20:
        scores['trend'] = 10
    total_score = sum(scores.values())
    return total_score, scores

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    raw_input = request.form["token"].strip()
    tokens_to_analyze = [t.strip() for t in raw_input.split(",") if t.strip()][:1]
    results = []
    for address in tokens_to_analyze:
        pair_data = get_dexscreener_data(address)
        if not pair_data:
            results.append({"token": address, "error": "Token non trouvé sur DexScreener."}); continue
        rugcheck_data = get_rugcheck_data(address)
        ai_hype_data = get_ai_hype_score(
            pair_data.get("baseToken", {}).get("name"),
            pair_data.get("baseToken", {}).get("symbol")
        )
        total_score, score_details = calculate_final_score(pair_data, rugcheck_data, ai_hype_data)
        results.append({
            "token": address, "token_name": pair_data.get("baseToken", {}).get("name"),
            "token_symbol": pair_data.get("baseToken", {}).get("symbol"),
            "current_price": float(pair_data.get("priceUsd", 0)),
            "market_cap": float(pair_data.get("fdv", 0)),
            "pair_address": pair_data.get("pairAddress"),
            "total_score": total_score, "score_details": score_details,
            "ai_reason": ai_hype_data.get('reason')
        })
    return render_template("results.html", results=results)

if __name__ == "__main__": app.run(debug=True)