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

# --- Fonctions d'API appelées par le serveur ---
def get_rugcheck_data(token_address):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
        response = requests.get(url, timeout=15)
        return response.json() if response.ok else None
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

    # --- Lancement de l'algorithme de scoring ---
    scores = { "security": 0, "activity": 0, "hype": 0, "trend": 0 }
    
    # 1. Sécurité (via API RugCheck)
    rugcheck_data = get_rugcheck_data(token_address)
    if rugcheck_data and rugcheck_data.get('risks'):
        sec_score = 40
        for risk in rugcheck_data['risks']:
            if risk['name'] == 'Mutable Metadata': sec_score -= 10
            if risk['name'] == 'Mint Authority Enabled': sec_score -= 20
            if risk['name'] == 'High Concentration of Holders': sec_score -= 10
        scores['security'] = max(0, sec_score)
    
    # 2. Volume / Activité (via données DexScreener)
    volume = dex_data.get('volume', {})
    txns = dex_data.get('txns', {}).get('h1', {})
    act_score = 0
    if volume.get('h6', 0) > 0 and volume.get('h1', 0) > (volume.get('h6', 0) / 6): act_score += 15
    if txns.get('buys', 0) > txns.get('sells', 0): act_score += 15
    scores['activity'] = act_score

    # 3. Tendance (via données DexScreener)
    price_change = dex_data.get('priceChange', {})
    if price_change.get('h6', 0) > 0 and price_change.get('m5', 0) > -20:
        scores['trend'] = 10
    
    # --- Interrogation de l'IA Gemini avec toutes les données ---
    prompt = f"""
    En tant qu'expert en analyse de memecoins Solana, analyse les données suivantes pour le token "{dex_data['baseToken']['name']}" (${dex_data['baseToken']['symbol']}).

    Données Techniques & Marché:
    - Market Cap: ${dex_data.get('fdv', 0):,.0f}
    - Liquidité: ${dex_data.get('liquidity', {}).get('usd', 0):,.0f}
    - Volume 24h: ${volume.get('h24', 0):,.0f}
    - Variation prix 1h/24h: {price_change.get('h1', 0)}% / {price_change.get('h24', 0)}%
    - Ratio Acheteurs/Vendeurs (1h): {txns.get('buys', 0)} acheteurs / {txns.get('sells', 0)} vendeurs
    - Score de sécurité (sur 40): {scores['security']}

    En te basant sur TOUTES ces données, fournis une analyse finale experte.
    Réponds UNIQUEMENT avec un objet JSON au format suivant:
    {{
      "hype_score": <un score de 0 à 100 estimant le hype actuel, basé sur le nom, le volume et l'activité acheteuse>,
      "final_verdict": "BUY NOW, POTENTIAL BUY, WAIT ou HIGH RISK",
      "probability": <une probabilité en % que le token performe bien à court terme (ex: 75)>,
      "summary": "<ton résumé personnalisé d'une phrase expliquant ta décision pour ce token spécifique>"
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        ai_data = json.loads(response.text.strip().replace("```json", "").replace("```", ""))
        scores['hype'] = round(ai_data.get('hype_score', 0) * 0.20)
    except Exception as e:
        logger.error(f"Erreur finale API Gemini: {e}")
        ai_data = {"final_verdict": "Erreur IA", "probability": 0, "summary": "L'analyse IA a échoué."}
        scores['hype'] = 0

    total_score = sum(scores.values())
    
    return jsonify({
        "total_score": total_score,
        "score_details": scores,
        "ai_analysis": ai_data
    })

# --- Routes de base ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    raw_input = request.form["token"].strip()
    tokens_to_analyze = [t.strip() for t in raw_input.split(",") if t.strip()][:1] # Limite à 1 pour la démo
    return render_template("results.html", tokens=tokens_to_analyze)

if __name__ == "__main__": app.run(debug=True)