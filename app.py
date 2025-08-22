from flask import Flask, render_template, request
import logging
import time
import os
import json
import google.generativeai as genai
from moralis import sol_api
import requests
from typing import Dict, Any, Optional

app = Flask(__name__)

# --- Configuration des API ---
try:
    app.config['GEMINI_API_KEY'] = os.environ['GEMINI_API_KEY']
    app.config['MORALIS_API_KEY'] = os.environ['MORALIS_API_KEY']
    genai.configure(api_key=app.config['GEMINI_API_KEY'])
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("INFO: Clés API chargées avec succès.")
except KeyError as e:
    print(f"ERREUR CRITIQUE: La variable d'environnement {e} est MANQUANTE !")
    model = None

# --- Fonctions de formatage ---
@app.template_filter()
def format_price(value):
    try:
        f_value = float(value)
        return f"${f_value:,.10f}".rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return "N/A"
@app.template_filter()
def format_market_cap(value):
    try:
        f_value = float(value)
        if f_value > 1_000_000_000: return f"${f_value/1_000_000_000:.2f}B"
        if f_value > 1_000_000: return f"${f_value/1_000_000:.2f}M"
        if f_value > 1_000: return f"${f_value/1_000:.2f}K"
        return f"${int(f_value)}"
    except (ValueError, TypeError):
        return "N/A"

# --- Services et Logique ---
class APIService:
    @staticmethod
    def get_rugcheck_data(token_address: str) -> Optional[Dict[str, Any]]:
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
            response = requests.get(url, timeout=15)
            return response.json() if response.ok else None
        except Exception as e:
            app.logger.error(f"Erreur API RugCheck: {e}"); return None

    @staticmethod
    def get_moralis_token_data(token_address: str) -> Optional[Dict[str, Any]]:
        if not app.config.get('MORALIS_API_KEY'): return None
        try:
            params = {"network": "mainnet", "address": token_address}
            return sol_api.token.get_token_price(api_key=app.config['MORALIS_API_KEY'], params=params)
        except Exception as e:
            app.logger.error(f"Erreur Moralis (token data): {e}"); return None

    @staticmethod
    def get_trending_tokens() -> tuple:
        if not app.config.get('MORALIS_API_KEY'): return [], "Clé API Moralis non configurée"
        try:
            params = {"network": "mainnet"}
            result = sol_api.market_data.get_top_spl_by_trading_volume(api_key=app.config['MORALIS_API_KEY'], params=params)
            return result[:10], None
        except Exception as e:
            app.logger.error(f"Erreur tendances Moralis: {e}")
            return [], str(e)

class AnalysisService:
    @staticmethod
    def get_final_analysis(token_data: Dict[str, Any], token_address: str) -> Dict[str, Any]:
        scores = {"security": 0, "activity": 0, "hype": 0, "trend": 0}
        
        # Sécurité
        rugcheck_data = APIService.get_rugcheck_data(token_address)
        if rugcheck_data and rugcheck_data.get('risks'):
            sec_score = 40
            for risk in rugcheck_data['risks']:
                if risk['name'] in ['Mutable Metadata', 'Mint Authority Enabled', 'High Concentration of Holders']: sec_score -= 15
            scores['security'] = max(0, sec_score)
        
        # Tendance
        price_change = float(token_data.get('price_change_24h_percent', 0))
        if price_change > 0: scores['trend'] = 10
        if price_change > 50: scores['activity'] = 15 # Simplification de l'activité
        
        # IA
        ai_data = {"final_verdict": "Indisponible", "probability": 0, "summary": "L'IA n'a pas pu être contactée."}
        if model:
            prompt = f"""Analyse ce token Solana: prix=${token_data.get('price_usd')}, variation 24h={price_change}%, score sécurité={scores['security']}/40.
            Réponds UNIQUEMENT en JSON: {{"hype_score": <0-100>, "final_verdict": "BUY, WAIT, ou HIGH RISK", "probability": <0-100>, "summary": "<1 phrase>"}}"""
            try:
                response = model.generate_content(prompt)
                cleaned_text = response.text.strip().replace("```json", "").replace("```", "")
                ai_data = json.loads(cleaned_text)
                scores['hype'] = round(ai_data.get('hype_score', 0) * 0.20)
            except Exception as e:
                app.logger.error(f"Erreur API Gemini: {e}")
        
        total_score = sum(scores.values())
        return {
            "total_score": total_score,
            "score_details": scores,
            "ai_analysis": ai_data
        }

# --- Routes des pages ---
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/tendances")
def tendances():
    trending_data, error = APIService.get_trending_tokens()
    return render_template("tendances.html", trending_data=trending_data, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    token_address = request.form.get("token", "").strip()
    if not token_address:
        return render_template("results.html", results=[{"error": "Adresse de token requise."}])

    token_data = APIService.get_moralis_token_data(token_address)
        
    if not token_data or "usdPrice" not in token_data:
        return render_template("results.html", results=[{"error": "Token non trouvé ou données de prix indisponibles."}])
    
    analysis_results = AnalysisService.get_final_analysis(token_data, token_address)
    
    result = {
        "token": token_address,
        "token_name": token_data.get("tokenName", "N/A"),
        "token_symbol": token_data.get("tokenSymbol", "N/A"),
        "current_price": token_data.get("usdPrice", 0),
        "market_cap": 0, # Note: cet endpoint ne fournit pas le Market Cap
    }
    result.update(analysis_results) # Fusionne les dictionnaires
    
    return render_template("results.html", results=[result])

if __name__ == "__main__":
    app.run(debug=True)