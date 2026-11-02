import re
import secrets
import time

from flask import (
    Blueprint, Response, abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for,
)

from .auth import clean_name, valid_email
from .db import get_db, now_iso
from .security import check_secret, hash_secret, login_required
from .services import setup_missing

bp = Blueprint("student", __name__)

PIN_RE = re.compile(r"^\d{4}$")
student_only = login_required("student")


def flow():
    return current_app.extensions["flow"]


def monitors():
    return current_app.extensions["monitors"]


def parse_coords(lat, lng):
    """Return (lat, lng) floats, or (None, None) if they are missing or out of range."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None, None
    if lat != lat or lng != lng or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return lat, lng


def visible_incident(row):
    """A duress alert must look cancelled on the student's own screens."""
    item = dict(row)
    if item["duress"]:
        item.update(state="cancelled", status=None, email_status=None)
    return item


def recent_incidents():
    rows = get_db().execute(
        "SELECT * FROM incidents WHERE user_id = ? AND state != 'counting' ORDER BY started_at DESC, id DESC LIMIT 5",
        (g.user["id"],),
    ).fetchall()
    return [visible_incident(r) for r in rows]


@bp.route("/dashboard")
@student_only
def dashboard():
    contact = get_db().execute("SELECT * FROM contacts WHERE user_id = ?", (g.user["id"],)).fetchone()
    return render_template(
        "dashboard.html",
        missing=setup_missing(g.user),
        recent=recent_incidents(),
        contact=contact,
        samples=monitors().sample_files(),
    )


@bp.route("/dashboard/recent")
@student_only
def recent():
    return render_template("_recent.html", recent=recent_incidents())


@bp.route("/setup")
@student_only
def setup():
    contact = get_db().execute("SELECT * FROM contacts WHERE user_id = ?", (g.user["id"],)).fetchone()
    return render_template("setup.html", contact=contact, missing=setup_missing(g.user))


@bp.route("/setup/contact", methods=("POST",))
@student_only
def save_contact():
    name = clean_name(request.form.get("name", ""))
    email = request.form.get("email", "").strip().lower()
    if not name or not valid_email(email):
        flash("Enter the contact's name and a valid email address. Nothing was saved.", "error")
        return redirect(url_for("student.setup"))
    if email == g.user["email"]:
        flash("A trusted contact must be someone else. Nothing was saved.", "error")
        return redirect(url_for("student.setup"))
    db = get_db()
    existing = db.execute("SELECT * FROM contacts WHERE user_id = ?", (g.user["id"],)).fetchone()
    if existing:
        # A new person gets a new private link, so the old one stops working.
        token = existing["token"] if existing["email"] == email else secrets.token_urlsafe(24)
        db.execute("UPDATE contacts SET name = ?, email = ?, token = ? WHERE id = ?", (name, email, token, existing["id"]))
    else:
        db.execute(
            "INSERT INTO contacts (user_id, name, email, token, created_at) VALUES (?, ?, ?, ?, ?)",
            (g.user["id"], name, email, secrets.token_urlsafe(24), now_iso()),
        )
    db.commit()
    flash("Trusted contact saved.", "success")
    return redirect(url_for("student.setup"))


@bp.route("/setup/pin", methods=("POST",))
@student_only
def save_pin():
    pin = request.form.get("pin", "")
    duress = request.form.get("duress_pin", "")
    current_duress = g.user["duress_pin_hash"]
    if not PIN_RE.match(pin):
        flash("The cancel PIN must be exactly 4 digits. Nothing was saved.", "error")
    elif duress and not PIN_RE.match(duress):
        flash("The duress PIN must be exactly 4 digits. Nothing was saved.", "error")
    elif duress and duress == pin:
        flash("The duress PIN must be different from the cancel PIN. Nothing was saved.", "error")
    elif not duress and check_secret(pin, current_duress):
        flash("This PIN matches your duress PIN. Choose another. Nothing was saved.", "error")
    else:
        db = get_db()
        db.execute(
            "UPDATE users SET pin_hash = ?, duress_pin_hash = ? WHERE id = ?",
            (hash_secret(pin), hash_secret(duress) if duress else current_duress, g.user["id"]),
        )
        db.commit()
        flash("PIN saved.", "success")
    return redirect(url_for("student.setup"))


@bp.route("/setup/location", methods=("POST",))
@student_only
def save_location():
    label = " ".join(request.form.get("label", "").split())[:120]
    if not label:
        flash("Describe your saved location, such as a hostel and room. Nothing was saved.", "error")
        return redirect(url_for("student.setup"))
    lat, lng = parse_coords(request.form.get("lat"), request.form.get("lng"))
    db = get_db()
    db.execute(
        "UPDATE users SET location_label = ?, location_lat = ?, location_lng = ? WHERE id = ?",
        (label, lat, lng, g.user["id"]),
    )
    db.commit()
    flash("Saved location updated.", "success")
    return redirect(url_for("student.setup"))


@bp.route("/history")
@student_only
def history():
    rows = get_db().execute(
        "SELECT * FROM incidents WHERE user_id = ? AND state != 'counting' ORDER BY started_at DESC, id DESC",
        (g.user["id"],),
    ).fetchall()
    return render_template("history.html", incidents=[visible_incident(r) for r in rows])


@bp.route("/help-map")
@student_only
def help_map():
    return render_template("help_map.html")


@bp.route("/api/state")
@student_only
def state():
    monitor = monitors().get(g.user["id"])
    return jsonify(
        monitoring=monitor is not None,
        person_visible=bool(monitor and monitor.person_visible),
        countdown=flow().active_for(g.user["id"]),
        missing=setup_missing(g.user),
    )


@bp.route("/api/monitor/start", methods=("POST",))
@student_only
def monitor_start():
    data = request.get_json(silent=True) or {}
    missing = setup_missing(g.user)
    if missing:
        return jsonify(error=f"Finish setup first: add your {', '.join(missing)}.", setup=True), 409
    if data.get("consent") is not True:
        return jsonify(error="Please accept the consent notice first."), 400
    source = data.get("source", "webcam")
    if source == "webcam":
        capture_source = 0
    elif source in monitors().sample_files():
        capture_source = str(current_app.config["SAMPLES_DIR"]) + "/" + source
    else:
        return jsonify(error="That video source is not available."), 400

    db = get_db()
    db.execute("UPDATE users SET consent_at = ? WHERE id = ?", (now_iso(), g.user["id"]))
    db.commit()

    from detection.monitor import CameraUnavailable
    from detection.pose import ModelMissing

    try:
        monitors().start(g.user["id"], capture_source)
    except ModelMissing:
        return jsonify(error="The pose model is not installed. Run scripts/download_model.py."), 503
    except CameraUnavailable:
        return jsonify(error="The webcam could not be opened. Check it is free, or use a recorded video."), 503
    except RuntimeError as error:
        return jsonify(error=str(error)), 409
    return jsonify(running=True)


@bp.route("/api/monitor/stop", methods=("POST",))
@student_only
def monitor_stop():
    monitors().stop(g.user["id"])
    flow().clear_location(g.user["id"])
    return jsonify(running=False)


@bp.route("/monitor/feed")
@student_only
def monitor_feed():
    monitor = monitors().get(g.user["id"])
    if monitor is None:
        abort(404)

    def frames():
        while not monitor.stopped:
            jpeg = monitor.latest_jpeg
            if jpeg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            time.sleep(0.1)

    response = Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/api/location", methods=("POST",))
@student_only
def update_location():
    data = request.get_json(silent=True) or {}
    lat, lng = parse_coords(data.get("lat"), data.get("lng"))
    if lat is None:
        return jsonify(error="Invalid location."), 400
    flow().update_location(g.user["id"], lat, lng)
    return jsonify(ok=True)


@bp.route("/api/sos", methods=("POST",))
@student_only
def sos():
    missing = setup_missing(g.user)
    if missing:
        return jsonify(error=f"Finish setup first: add your {', '.join(missing)}.", setup=True), 409
    return jsonify(flow().start(g.user["id"], "SOS"))


@bp.route("/api/incidents/<int:incident_id>/cancel", methods=("POST",))
@student_only
def cancel(incident_id):
    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", ""))
    if not PIN_RE.match(pin):
        return jsonify(result="wrong_pin")
    return jsonify(result=flow().cancel(incident_id, g.user["id"], pin))


@bp.route("/events")
@login_required()
def events():
    broker = current_app.extensions["broker"]
    channel = "admin" if g.user["role"] == "admin" else f"user:{g.user['id']}"
    response = Response(broker.stream(channel), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
