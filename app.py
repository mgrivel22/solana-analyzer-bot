from flask import Flask, render_template, request
import json

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    raw_input = request.form["token"].strip()
    # On sépare juste les adresses et on les envoie au template
    tokens_to_analyze = [t.strip() for t in raw_input.split(",") if t.strip()]
    
    # On limite toujours le nombre pour éviter les abus
    tokens_to_analyze = tokens_to_analyze[:3]
    
    return render_template("results.html", tokens=tokens_to_analyze)

if __name__ == "__main__":
    app.run(debug=True)