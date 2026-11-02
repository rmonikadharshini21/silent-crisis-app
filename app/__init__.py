import os
import pathlib
import secrets
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, render_template

from . import db, security
from .events import Broker
from .services import Flow, Monitors

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _secret_key(instance):
    path = instance / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _seed_admin(app):
    email = app.config["ADMIN_EMAIL"].strip().lower()
    password = app.config["ADMIN_PASSWORD"]
    with app.app_context():
        database = db.get_db()
        if database.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone():
            return
        if not (email and password):
            app.logger.warning("No admin account: set ADMIN_EMAIL and ADMIN_PASSWORD.")
            return
        database.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at)"
            " VALUES ('Campus Admin', ?, ?, 'admin', ?)",
            (email, security.hash_secret(password), db.now_iso()),
        )
        database.commit()


def create_app(test_config=None):
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.example")  # Fills in anything .env leaves out.
    instance = ROOT / "instance"
    instance.mkdir(exist_ok=True)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_secret_key(instance),
        DATABASE=str(instance / "silent_crisis.db"),
        SAMPLES_DIR=str(ROOT / "samples"),
        HOST=os.getenv("HOST", "127.0.0.1"),
        PORT=int(os.getenv("PORT", "5000")),
        BASE_URL=os.getenv("BASE_URL", "http://127.0.0.1:5000").rstrip("/"),
        COUNTDOWN_SECONDS=float(os.getenv("COUNTDOWN_SECONDS", "10")),
        CONFIDENCE_THRESHOLD=float(os.getenv("CONFIDENCE_THRESHOLD", "0.6")),
        ADMIN_EMAIL=os.getenv("ADMIN_EMAIL", ""),
        ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", ""),
        SMTP_HOST=os.getenv("SMTP_HOST", ""),
        SMTP_PORT=int(os.getenv("SMTP_PORT", "587")),
        SMTP_USER=os.getenv("SMTP_USER", ""),
        SMTP_PASSWORD=os.getenv("SMTP_PASSWORD", ""),
        SMTP_FROM=os.getenv("SMTP_FROM", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    security.init_app(app)

    broker = Broker()
    app.extensions["broker"] = broker
    app.extensions["monitors"] = Monitors(app, broker)
    app.extensions["flow"] = Flow(app, broker)

    from .admin import bp as admin_bp
    from .auth import bp as auth_bp
    from .contact import bp as contact_bp
    from .student import bp as student_bp

    for blueprint in (auth_bp, student_bp, admin_bp, contact_bp):
        app.register_blueprint(blueprint)

    for code, title in ((400, "Request not accepted"), (403, "No access"), (404, "Page not found")):
        app.register_error_handler(code, _error_page(code, title))

    _seed_admin(app)
    app.extensions["flow"].recover_stale()
    return app


def _error_page(code, title):
    def handler(_error):
        return render_template("error.html", code=code, title=title), code

    return handler
