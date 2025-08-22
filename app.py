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
    GEMINI_API_KEY = os.environ['GEMINI_API_KEY']
    MORALIS_API_KEY = os.environ['MORALIS_API_KEY']
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
def get_moralis_token_data(token_address):
    if not MORALIS_API_KEY: return None
    try:
        url = f"https://solana-gateway.moralis.io/api/v2/token/{token_address}/price"
        headers = {"accept": "application/json", "X-API-Key": MORALIS_API_KEY}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Erreur API Moralis (token data): {e}"); return None

def get_rugcheck_data(token_address):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
        response = requests.get(url, timeout=15)
        return response.json() if response.ok else None
    except Exception as e:
        logger.error(f"Erreur API RugCheck: {e}"); return None

def get_final_analysis_and_score(token_data, token_address):
    scores = {"security": 0, "activity": 0, "hype": 0, "trend": 0}
    rugcheck_data = get_rugcheck_data(token_address)
    if rugcheck_data and rugcheck_data.get('risks'):
        sec_score = 40
        for risk in rugcheck_data['risks']:
            if risk['name'] in ['Mutable Metadata', 'Mint Authority Enabled', 'High Concentration of Holders']: sec_score -= 15
        scores['security'] = max(0, sec_score)
    
    # Moralis ne fournit pas toutes les données (volume, txns) dans cet endpoint simple
    # On simplifie donc cette partie en se basant sur le prix
    price_change = token_data.get('usdPriceChange24hr', 0)
    if price_change is not None:
        if price_change > 0: scores['trend'] = 10
        if price_change > 50: scores['activity'] = 15 # Grosse activité positive
    
    ai_data = {"final_verdict": "Indisponible", "probability": 0, "summary": "L'analyse IA a échoué."}
    if model:
        prompt = f"""Analyse le token avec le prix de ${token_data.get('usdPrice', 0):.6f} et une variation de {price_change}% sur 24h. Son score de sécurité est de {scores['security']}/40.
        Réponds UNIQUEMENT en JSON: {{"hype_score": <0-100>, "final_verdict": "BUY, WAIT, ou HIGH RISK", "probability": <0-100>, "summary": "<1 phrase>"}}"""
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
    trending_data, error = [], None
    try:
        url = "https://solana-gateway.moralis.io/api/v2/market-data/spl/top-movers"
        headers = {"accept": "application/json", "X-API-Key": MORALIS_API_KEY}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        trending_data = data.get('top_gainers', [])[:10]
    except Exception as e:
        logger.error(f"Erreur récupération tendances Moralis: {e}")
        error = "Impossible de charger les données des tendances."
    return render_template("tendances.html", trending_data=trending_data, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    token_address = request.form["token"].strip()
    results = []
    token_data = get_moralis_token_data(token_address)
    if not token_data:
        results.append({"token": token_address, "error": "Token non trouvé via Moralis."})
    else:
        total_score, score_details, ai_data = get_final_analysis_and_score(token_data, token_address)
        results.append({
            "token": token_address, "token_name": token_data.get("tokenName", "N/A"), "token_symbol": token_data.get("tokenSymbol", "N/A"),
            "current_price": float(token_data.get("usdPrice", 0)), "market_cap": 0, # L'endpoint prix simple ne donne pas le MC
            "total_score": total_score, "score_details": score_details, "ai_analysis": ai_data,
            "pair_address": None # Pas de paire directe depuis cet endpoint
        })
    return render_template("results.html", results=results)

if __name__ == "__main__":
    app.run(debug=True)