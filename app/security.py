import functools
import hmac
import secrets
import threading
import time

import bcrypt
from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from .db import get_db

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300


def hash_secret(value):
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()


def check_secret(value, hashed):
    if not hashed:
        return False
    return bcrypt.checkpw(value.encode(), hashed.encode())


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


class LoginLimiter:
    """Counts failed logins per email and client address, in memory."""

    def __init__(self):
        self._fails = {}
        self._lock = threading.Lock()

    def blocked(self, key):
        cutoff = time.monotonic() - LOGIN_WINDOW_SECONDS
        with self._lock:
            recent = [t for t in self._fails.get(key, []) if t > cutoff]
            self._fails[key] = recent
            return len(recent) >= LOGIN_ATTEMPTS

    def fail(self, key):
        with self._lock:
            self._fails.setdefault(key, []).append(time.monotonic())

    def clear(self, key):
        with self._lock:
            self._fails.pop(key, None)


def wants_json():
    return request.path.startswith(("/api/", "/admin/api/")) or request.path == "/events"


def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if g.user is None:
            session.clear()


def login_required(role=None):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                if wants_json():
                    return jsonify(error="Please log in."), 401
                return redirect(url_for("auth.login"))
            if role and g.user["role"] != role:
                if wants_json():
                    return jsonify(error="You do not have access."), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def protect_csrf():
    if request.method not in UNSAFE_METHODS:
        return
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not hmac.compare_digest(sent.encode(), session.get("csrf", "\0").encode()):
        if wants_json():
            return jsonify(error="Your session expired. Reload the page."), 400
        abort(400, "Your session expired. Reload the page and try again.")


def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # Alert links carry a token, so send other sites the origin only.
    # OpenStreetMap's tile servers refuse requests with no referrer at all.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://unpkg.com; "
        "style-src 'self' https://unpkg.com; "
        "img-src 'self' data: https://tile.openstreetmap.org https://unpkg.com; "
        "connect-src 'self' https://overpass-api.de; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    return response


def init_app(app):
    app.before_request(load_user)
    app.before_request(protect_csrf)
    app.after_request(security_headers)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.extensions["login_limiter"] = LoginLimiter()


def login_limiter():
    return current_app.extensions["login_limiter"]
