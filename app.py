from flask import Flask, render_template, request
import requests
import logging
import time

app = Flask(__name__)

# ... (Les filtres de formatage restent les mêmes) ...
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

# ... (L'analyse stratégique reste la même) ...
def analyze_token_strategy(pair_data):
    reasons = []
    liquidity = pair_data.get("liquidity", {}).get("usd", 0)
    if liquidity < 3000: return "Risque Élevé", "wait", ["🚩 Liquidité critique (< 3k$)"]
    pair_created_at = pair_data.get("pairCreatedAt", 0) / 1000
    if (time.time() - pair_created_at) < 3600: reasons.append("⚠️ Token très récent (< 1h)")
    score = 0
    price_change = pair_data.get("priceChange", {})
    if price_change.get("h1", 0) > 15: score += 1; reasons.append("📈 Momentum 1h (> +15%)")
    if price_change.get("h24", 0) > 0: score += 1; reasons.append("✅ Tendance 24h positive")
    if price_change.get("m5", 0) < -10: score -= 1; reasons.append("📉 Dump récent 5min (< -10%)")
    volume = pair_data.get("volume", {})
    if volume.get("h24", 0) > 50000: score += 1; reasons.append("📊 Volume 24h significatif (> 50k$)")
    txns = pair_data.get("txns", {}).get("h1", {})
    buys = txns.get("buys", 0)
    sells = txns.get("sells", 0)
    if buys > sells * 1.5: score += 2; reasons.append("🔥 Forte pression acheteuse 1h")
    elif buys > sells: reasons.append("👍 Sentiment acheteur positif 1h")
    fdv = pair_data.get("fdv", 0)
    if fdv < 250000 and fdv > 10000: score += 1; reasons.append("💎 Potentiel (MC < 250k$)")
    if score >= 4: return "Signal d'Achat Fort", "buy", reasons
    elif score >= 2: return "Potentiel Intéressant", "hold", reasons
    elif score >= 0: return "Neutre / À Surveiller", "hold", reasons
    else: return "Prudence Requise", "wait", reasons

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_dexscreener_data(token_or_pair_address):
    # MESSAGE DE TEST AJOUTÉ ICI
    logger.info("--- Exécution de la fonction get_dexscreener_data VERSION 2 ---")
    try:
        url = f"https://api.dexscreener.com/latest/dex/search?q={token_or_pair_address}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 1.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        if data.get("pairs"):
            return data["pairs"][0]
        else:
            return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur API DexScreener pour {token_or_pair_address}: {e}")
        return None

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    raw_input = request.form["token"].strip()
    tokens_to_analyze = [t.strip() for t in raw_input.split(",") if t.strip()]
    results = []
    for address in tokens_to_analyze[:3]:
        pair_data = get_dexscreener_data(address)
        if not pair_data:
            results.append({"token": address, "error": "Token non trouvé. Vérifiez l'adresse."})
            continue
        signal, signal_key, reasons = analyze_token_strategy(pair_data)
        results.append({
            "token": address,
            "token_name": pair_data.get("baseToken", {}).get("name"),
            "token_symbol": pair_data.get("baseToken", {}).get("symbol"),
            "current_price": float(pair_data.get("priceUsd", 0)),
            "market_cap": float(pair_data.get("fdv", 0)),
            "pair_address": pair_data.get("pairAddress"),
            "signal": signal,
            "signal_key": signal_key,
            "reasons": reasons
        })
    return render_template("results.html", results=results)

if __name__ == "__main__":
    app.run(debug=True)