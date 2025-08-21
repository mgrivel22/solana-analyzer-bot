from flask import Flask, render_template, request

app = Flask(__name__)

@app.route("/")
def index():
    """Affiche la page d'accueil."""
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    """Récupère les adresses des tokens et les envoie à la page de résultats."""
    raw_input = request.form["token"].strip()
    # On sépare les adresses fournies par l'utilisateur
    tokens_to_analyze = [t.strip() for t in raw_input.split(",") if t.strip()]
    
    # On limite le nombre pour éviter les abus
    tokens_to_analyze = tokens_to_analyze[:3]
    
    # On envoie la liste des adresses (la variable 'tokens') au template
    return render_template("results.html", tokens=tokens_to_analyze)

if __name__ == "__main__":
    app.run(debug=True)