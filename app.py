"""UAT Test Management Tool - Flask application entry point."""
import os

from flask import Flask

from database import init_db

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.config["DATABASE"] = os.path.join(app.root_path, "uat.db")

# Initialize database and register teardown
with app.app_context():
    init_db(app)

from database import close_db
app.teardown_appcontext(close_db)

from routes import register_routes

register_routes(app)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
