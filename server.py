from flask import Flask
from flask_cors import CORS

from src.grok_researcher import init_researcher
from src.routes import register_routes

app = Flask(__name__)
CORS(app)

# Initialize Grok Researcher
init_researcher(app.logger)

# Register routes
register_routes(app)


if __name__ == "__main__":
  import os

  import waitress

  if os.environ.get("DEV"):
    app.run(debug=True, host="0.0.0.0", port=5000)
  else:
    waitress.serve(app, host="0.0.0.0", port=5000)
