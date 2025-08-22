from flask import Flask, render_template, request
import logging
import time
import os
import json
import google.generativeai as genai
from moralis import sol_api
from typing import Dict, Any, List, Optional

app = Flask(__name__)

# Configuration
# It's recommended to set these as environment variables for security
app.config['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY')
app.config['MORALIS_API_KEY'] = os.environ.get('MORALIS_API_KEY')

# API Initialization
try:
    genai.configure(api_key=app.config['GEMINI_API_KEY'])
    model = genai.GenerativeModel('gemini-1.5-flash')
    print("INFO: Gemini API configured successfully")
except Exception as e:
    print(f"ERROR: Gemini API configuration failed - {e}")
    model = None

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Template Filters
@app.template_filter()
def format_price(value: float) -> str:
    """Formats a float into a USD price string, removing trailing zeros."""
    try:
        value = float(value)
        return f"${value:,.10f}".rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return "N/A"

@app.template_filter()
def format_market_cap(value: float) -> str:
    """Formats a large number into a human-readable market cap string (B, M, K)."""
    try:
        value = float(value)
        if value >= 1_000_000_000:
            return f"${value/1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"${value/1_000_000:.2f}M"
        elif value >= 1_000:
            return f"${value/1_000:.2f}K"
        return f"${value:,.2f}"
    except (ValueError, TypeError):
        return "N/A"

# Services
class MoralisService:
    @staticmethod
    def get_token_data(token_address: str) -> Optional[Dict[str, Any]]:
        """Fetches price and metadata for a specific SPL token."""
        try:
            params = {"network": "mainnet", "address": token_address}
            return sol_api.token.get_token_price(
                api_key=app.config['MORALIS_API_KEY'], params=params
            )
        except Exception as e:
            logger.error(f"Moralis get_token_data error: {e}")
            return None

    @staticmethod
    def get_trending_tokens() -> tuple:
        """
        Fetches the top 10 trending SPL tokens by 24h trading volume.
        FIX: Corrected the API call to use the valid method.
        """
        try:
            params = {"network": "mainnet"}
            # The original call 'sol_api.market_data.get_top_spl_by_trading_volume' is incorrect.
            # The correct method is sol_api.market_data.get_top_spl_tokens_by_24hr_volume()
            result = sol_api.market_data.get_top_spl_tokens_by_24hr_volume(
                api_key=app.config['MORALIS_API_KEY'], params=params
            )
            # Ensure the returned data has the keys the template expects
            # The API returns a list of dictionaries.
            return result.get('tokens', [])[:10], None
        except Exception as e:
            logger.error(f"Moralis get_trending_tokens error: {e}")
            return [], str(e)

class AIService:
    @staticmethod
    def analyze_token(token_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyzes token data using the Gemini AI model."""
        if not model:
            logger.error("AI model not initialized.")
            return None

        prompt = f"""
        Analyze the Solana token with the following data:
        - Name: {token_data.get('token_name', 'N/A')}
        - Symbol: {token_data.get('token_symbol', 'N/A')}
        - Address: {token_data.get('token_address', 'N/A')}
        - Current Price (USD): {token_data.get('current_price', 'N/A')}
        - 24h Price Change (%): {token_data.get('price_change', 'N/A')}

        Based on this limited information, perform a brief risk analysis.

        Return your response ONLY in JSON format, with no other text or markdown.
        The JSON object must have these exact keys:
        - "total_score": A global risk score out of 100 (0=very high risk, 100=very low risk).
        - "final_verdict": A short, direct investment verdict from this list: "BUY NOW", "POTENTIAL BUY", "HOLD", "WAIT", "HIGH-RISK".
        - "probability": An estimated probability (as an integer) of a positive trend in the short term.
        - "summary": A very brief, one-sentence summary explaining your reasoning.

        Example JSON output:
        {{
          "total_score": 75,
          "final_verdict": "POTENTIAL BUY",
          "probability": 60,
          "summary": "The token shows a positive 24-hour change, suggesting recent momentum, but further research is needed."
        }}
        """
        try:
            response = model.generate_content(prompt)
            # Clean the response to ensure it's valid JSON
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(cleaned_response)
        except Exception as e:
            logger.error(f"Gemini AI analysis error: {e}")
            return {
                "total_score": 0,
                "final_verdict": "ERROR",
                "probability": 0,
                "summary": "The AI analysis failed to complete. Please try again."
            }

# Routes
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/tendances")
def tendances():
    if not app.config['MORALIS_API_KEY']:
        return render_template("tendances.html", error="Moralis API key not configured.")

    trending_data, error = MoralisService.get_trending_tokens()
    
    # Data transformation to match template keys
    transformed_data = []
    for token in trending_data:
        transformed_data.append({
            'logo': token.get('logo'),
            'name': token.get('name'),
            'symbol': token.get('symbol'),
            'price_usd': token.get('price_usd'),
            'price_change_24h_percent': token.get('price_change_24h_percent'),
            'token_address': token.get('token_address')
        })

    return render_template("tendances.html", trending_data=transformed_data, error=error)

@app.route("/analyze", methods=["POST"])
def analyze():
    token_address = request.form.get("token", "").strip()
    if not token_address:
        return render_template("results.html", results=[{"error": "Token address is required."}])

    # 1. Get data from Moralis
    token_data = MoralisService.get_token_data(token_address)
    if not token_data or "usdPrice" not in token_data:
        return render_template("results.html", results=[{"error": "Token not found or Moralis API error."}])

    # 2. Prepare data for analysis and rendering
    result = {
        "token": token_address, # The template uses 'token' for links
        "token_address": token_address,
        "token_name": token_data.get("tokenName", "N/A"),
        "token_symbol": token_data.get("tokenSymbol", "N/A"),
        "current_price": token_data.get("usdPrice", 0),
        "price_change": token_data.get("usdPriceChange24h", 0),
        "pair_address": token_data.get("address", "N/A")
    }

    # 3. Get AI Analysis (New Feature)
    ai_analysis_result = AIService.analyze_token(result)
    if ai_analysis_result:
        result["ai_analysis"] = ai_analysis_result
        result["total_score"] = ai_analysis_result.get("total_score", 0)
    else:
        result["error"] = "AI analysis could not be performed."
        result["total_score"] = 0
        result["ai_analysis"] = {
            "final_verdict": "N/A", "probability": 0, "summary": "Analysis failed."
        }

    return render_template("results.html", results=[result])

# Error Handlers
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Server Error 500: {e}")
    return render_template("500.html"), 500

if __name__ == "__main__":
    app.run(debug=False, host='0.0.0.0', port=5000)