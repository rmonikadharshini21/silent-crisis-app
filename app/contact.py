"""Pages for trusted contacts. Access is by private link, with no account."""
from flask import Blueprint, Response, abort, current_app, render_template

from .db import get_db
from .services import osm_link

bp = Blueprint("contact", __name__)


def _contact_or_404(token):
    row = get_db().execute(
        "SELECT c.*, u.name AS student FROM contacts c JOIN users u ON u.id = c.user_id WHERE c.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        abort(404)
    return row


@bp.route("/c/<token>")
def inbox(token):
    contact = _contact_or_404(token)
    alerts = get_db().execute(
        "SELECT * FROM incidents WHERE user_id = ? AND state = 'alerted' ORDER BY alerted_at DESC, id DESC",
        (contact["user_id"],),
    ).fetchall()
    return render_template("contact_inbox.html", contact=contact, alerts=alerts)


@bp.route("/c/<token>/events")
def inbox_events(token):
    _contact_or_404(token)
    broker = current_app.extensions["broker"]
    response = Response(broker.stream(f"contact:{token}"), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.route("/alert/<token>")
def alert_page(token):
    db = get_db()
    incident = db.execute(
        "SELECT i.*, u.name AS student, c.token AS contact_token FROM incidents i"
        " JOIN users u ON u.id = i.user_id LEFT JOIN contacts c ON c.user_id = i.user_id"
        " WHERE i.token = ? AND i.state = 'alerted'",
        (token,),
    ).fetchone()
    if incident is None:
        abort(404)
    return render_template(
        "alert.html", incident=incident, map_link=osm_link(incident["location_lat"], incident["location_lng"])
    )
