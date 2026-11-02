import re

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from .db import get_db, now_iso
from .security import check_secret, hash_secret, login_limiter

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DUMMY_HASH = hash_secret("timing-guard")


def valid_email(value):
    return bool(EMAIL_RE.match(value)) and len(value) <= 254


def clean_name(value):
    return " ".join(value.split())[:80]


def home_for(user):
    return url_for("admin.dashboard") if user["role"] == "admin" else url_for("student.dashboard")


def _begin_session(user_id):
    session.clear()
    session.permanent = True
    session["user_id"] = user_id


@bp.route("/")
def landing():
    return render_template("landing.html")


@bp.route("/signup", methods=("GET", "POST"))
def signup():
    if g.user:
        return redirect(home_for(g.user))
    if request.method == "POST":
        name = clean_name(request.form.get("name", ""))
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        if not name:
            error = "Please enter your name."
        elif not valid_email(email):
            error = "Please enter a valid email address."
        elif len(password) < 8 or len(password.encode()) > 72:
            error = "Password must be 8 to 72 characters."
        else:
            db = get_db()
            if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                error = "An account with this email already exists."
        if error:
            flash(error, "error")
            return render_template("signup.html", name=name, email=email), 400
        cursor = db.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name, email, hash_secret(password), now_iso()),
        )
        db.commit()
        _begin_session(cursor.lastrowid)
        flash("Account created. Finish setup to turn on protection.", "success")
        return redirect(url_for("student.setup"))
    return render_template("signup.html", name="", email="")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(home_for(g.user))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        key = f"{email}|{request.remote_addr}"
        limiter = login_limiter()
        if limiter.blocked(key):
            flash("Too many failed attempts. Try again in 5 minutes.", "error")
            return render_template("login.html", email=email), 429
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        ok = len(password.encode()) <= 72 and check_secret(password, user["password_hash"] if user else DUMMY_HASH)
        if not (user and ok):
            limiter.fail(key)
            flash("Email or password is incorrect.", "error")
            return render_template("login.html", email=email), 401
        limiter.clear(key)
        _begin_session(user["id"])
        return redirect(home_for(user))
    return render_template("login.html", email="")


@bp.route("/logout", methods=("POST",))
def logout():
    if g.user:
        from flask import current_app

        current_app.extensions["monitors"].stop(g.user["id"])
    session.clear()
    return redirect(url_for("auth.landing"))
