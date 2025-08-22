from flask import Flask, render_template, request, jsonify
import logging
import os
import json
import requests
from typing import Dict, Any, Optional, List

# --- Initialisation de Flask ---
app = Flask(__name__)

# --- Configuration ---
app.config['BIRDEYE_API_KEY'] = os.environ.get('BIRDEYE_API_KEY')
app.config['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY')

# --- Initialisation de l'API Gemini ---
model = None
if app.config['GEMINI_API_KEY']:
    try:
        import google.generativeai as genai
        genai.configure(api_key=app.config['GEMINI_API_KEY'])
        model = genai.GenerativeModel('gemini-1.5-flash')
        logging.info("INFO: API Gemini configurée avec succès")
    except Exception as e:
        logging.error(f"ERREUR: La configuration de l'API Gemini a échoué - {e}")

# --- Configuration du Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Filtres Jinja2 ---
@app.template_filter()
def format_number(value):
    try:
        value = float(value)
        if value >= 1_000_000_000: return f"{value/1_000_000_000:.2f}B"
        if value >= 1_000_000: return f"{value/1_000_000:.2f}M"
        if value >= 1_000: return f"{value/1_000:.2f}K"
        return f"{value:,.2f}"
    except (ValueError, TypeError): return "N/A"

# --- Services (uniquement pour les tendances) ---
class BirdeyeService:
    @staticmethod
    def get_trending_tokens() -> tuple[List[Dict[str, Any]], Optional[str]]:
        url = f"https://public-api.birdeye.so/defi/tokenlist?sort_by=v24hUSD&sort_type=desc&limit=50"
        headers = {"X-API-KEY": app.config['BIRDEYE_API_KEY']}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return (data.get('data', {}).get('tokens', []), None) if data.get('success') else ([], "Réponse invalide")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur API Birdeye (get_trending_tokens): {e}")
            return [], str(e)

# --- Routes Flask ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyzer")
def analyzer():
    # Sert simplement la page HTML. Toute la logique est maintenant côté client.
    return render_template("analyzer.html")

@app.route("/tendances")
def tendances():
    trending_data, error = BirdeyeService.get_trending_tokens()
    return render_template("tendances.html", trending_data=trending_data, error=error)

# --- NOUVELLE ROUTE API ---
@app.route("/api/gemini-analysis", methods=["POST"])
def gemini_analysis_proxy():
    if not model:
        return jsonify({"error": "Le service IA n'est pas configuré sur le serveur."}), 500

    token_data = request.json
    if not token_data:
        return jsonify({"error": "Aucune donnée de token fournie."}), 400

    # Préparation du prompt pour Gemini
    prompt = f"""
    Analyse ce token Solana avec les données de DexScreener : {json.dumps(token_data)}.
    Agis comme un analyste crypto expert et concis.
    Fournis une analyse structurée.
    1. "verdict": Un verdict d'investissement unique et direct parmi : "STRONG BUY", "BUY", "HOLD", "SELL", "HIGH-RISK".
    2. "risk_score": Un score de risque de 1 (très faible) à 10 (très élevé).
    3. "positive_points": Une liste de 2 à 3 points positifs clés (en français).
    4. "negative_points": Une liste de 2 à 3 points négatifs ou risques (en français).
    5. "summary": Un résumé final d'une phrase expliquant ta recommandation.
    Retourne ta réponse UNIQUEMENT en format JSON valide.
    """
    try:
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
        ai_analysis = json.loads(cleaned_response)
        return jsonify(ai_analysis)
    except Exception as e:
        logging.error(f"Erreur analyse Gemini: {e}")
        return jsonify({"error": "L'analyse par l'IA a échoué.", "summary": str(e)}), 500

# --- Gestionnaires d'Erreurs ---
@app.errorhandler(404)
def not_found(e): return render_template("404.html"), 404
@app.errorhandler(500)
def server_error(e): logging.error(f"Erreur Serveur 500: {e}"); return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(debug=True)
