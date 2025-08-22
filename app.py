from flask import Flask, render_template, request, jsonify
import requests
import logging
import time
import os
import json
import google.generativeai as genai

app = Flask(__name__)

# --- Configuration de l'API Google AI ---
try:
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    if not GEMINI_API_KEY:
        print("ATTENTION: Clé API Gemini non trouvée.")
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

# --- Fonctions d'API appelées par le serveur ---
def get_rugcheck_data(token_address):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Erreur API RugCheck: {e}"); return None

# --- Le cerveau : L'IA et l'Algorithme de Scoring ---
@app.route('/api/get_final_analysis', methods=['POST'])
def get_final_analysis():
    if not model:
        return jsonify({"error": "IA non configurée sur le serveur."}), 500

    dex_data = request.json.get('dex_data')
    token_address = request.json.get('token_address')

    if not dex_data or not token_address:
        return jsonify({"error": "Données manquantes."}), 400

    scores = { "security": 0, "activity": 0, "hype": 0, "trend": 0 }
    rugcheck_data = get_rugcheck_data(token_address)
    if rugcheck_data and rugcheck_data.get('risks'):
        sec_score = 40
        for risk in rugcheck_data['risks']:
            if risk['name'] == 'Mutable Metadata': sec_score -= 10
            if risk['name'] == 'Mint Authority Enabled': sec_score -= 20
            if risk['name'] == 'High Concentration of Holders': sec_score -= 10
        scores['security'] = max(0, sec_score)
    
    volume = dex_data.get('volume', {})
    txns = dex_data.get('txns', {}).get('h1', {})
    act_score = 0
    if volume.get('h6', 0) > 0 and volume.get('h1', 0) > (volume.get('h6', 0) / 6): act_score += 15
    if txns.get('buys', 0) > txns.get('sells', 0): act_score += 15
    scores['activity'] = act_score

    price_change = dex_data.get('priceChange', {})
    if price_change.get('h6', 0) > 0 and price_change.get('m5', 0) > -20:
        scores['trend'] = 10
    
    prompt = f"""
    Analyse les données suivantes pour le token "{dex_data['baseToken']['name']}" (${dex_data['baseToken']['symbol']}).
    - Market Cap: ${dex_data.get('fdv', 0):,.0f}
    - Liquidité: ${dex_data.get('liquidity', {}).get('usd', 0):,.0f}
    - Volume 24h: ${volume.get('h24', 0):,.0f}
    - Variation prix 1h/24h: {price_change.get('h1', 0)}% / {price_change.get('h24', 0)}%
    - Ratio Acheteurs/Vendeurs (1h): {txns.get('buys', 0)} acheteurs / {txns.get('sells', 0)} vendeurs
    - Score de sécurité (sur 40): {scores['security']}
    En te basant sur TOUTES ces données, fournis une analyse finale experte.
    Réponds UNIQUEMENT avec un objet JSON au format suivant:
    {{
      "hype_score": <un score de 0 à 100 estimant le hype actuel>,
      "final_verdict": "BUY NOW, POTENTIAL BUY, WAIT ou HIGH RISK",
      "probability": <une probabilité en % que le token performe bien à court terme>,
      "summary": "<ton résumé personnalisé d'une phrase expliquant ta décision>"
    }}
    """
    
    ai_data = {}
    try:
        response = model.generate_content(prompt)
        # Nettoyage robuste pour extraire le JSON même s'il est mal formaté
        cleaned_text = response.text.strip()
        json_start = cleaned_text.find('{')
        json_end = cleaned_text.rfind('}') + 1
        if json_start != -1 and json_end != -1:
            json_str = cleaned_text[json_start:json_end]
            ai_data = json.loads(json_str)
            scores['hype'] = round(ai_data.get('hype_score', 0) * 0.20)
        else:
            raise ValueError("Aucun JSON valide trouvé dans la réponse de l'IA")
    except Exception as e:
        logger.error(f"Erreur finale API Gemini ou parsing JSON: {e}")
        ai_data = {"final_verdict": "Erreur IA", "probability": 0, "summary": "L'analyse IA a échoué à cause d'une réponse inattendue."}
        scores['hype'] = 0

    total_score = sum(scores.values())
    return jsonify({
        "total_score": total_score,
        "score_details": scores,
        "ai_analysis": ai_data
    })

# --- Routes des pages ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/tendances")
def tendances():
    try:
        global_res = requests.get("https://api.coingecko.com/api/v3/global")
        global_data = global_res.json()['data']
        trending_res = requests.get("https://api.coingecko.com/api/v3/search/trending")
        trending_data = trending_res.json()['coins']
        market_health_change = global_data.get('market_cap_change_percentage_24h_usd', 0)
        if market_health_change > 2: market_health = {"status": "Bon", "color": "#28a745"}
        elif market_health_change < -2: market_health = {"status": "Mauvais", "color": "#dc3545"}
        else: market_health = {"status": "Neutre", "color": "#ffc107"}
    except Exception as e:
        logger.error(f"Erreur récupération tendances: {e}")
        global_data, trending_data, market_health = None, None, {"status": "Erreur", "color": "gray"}
    return render_template("tendances.html", global_data=global_data, trending_data=trending_data, market_health=market_health)

@app.route("/analyze", methods=["POST"])
def analyze():
    raw_input = request.form["token"].strip()
    tokens_to_analyze = [t.strip() for t in raw_input.split(",") if t.strip()][:1]
    return render_template("results.html", tokens=tokens_to_analyze)

if __name__ == "__main__": app.run(debug=True)