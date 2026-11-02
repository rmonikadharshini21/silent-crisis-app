from flask import Blueprint, current_app, jsonify, render_template, request, url_for

from .db import get_db
from .security import login_required
from .services import osm_link

bp = Blueprint("admin", __name__, url_prefix="/admin")

admin_only = login_required("admin")
STATUSES = ("Acknowledged", "Help sent", "Resolved", "False alarm")


def serialize(row):
    return {
        "id": row["id"],
        "student": row["student"],
        "student_email": row["student_email"],
        "contact": row["contact_name"],
        "alerted_at": row["alerted_at"],
        "trigger": row["trigger_source"],
        "confidence": row["confidence"],
        "status": row["status"],
        "duress": bool(row["duress"]),
        "location_label": row["location_label"],
        "location_source": row["location_source"],
        "map_link": osm_link(row["location_lat"], row["location_lng"]),
        "email_status": row["email_status"],
        "all_clear": bool(row["all_clear_at"]),
        "alert_page": url_for("contact.alert_page", token=row["token"]),
    }


@bp.route("")
@admin_only
def dashboard():
    return render_template("admin.html", statuses=STATUSES)


@bp.route("/api/incidents")
@admin_only
def incidents():
    rows = get_db().execute(
        "SELECT i.*, u.name AS student, u.email AS student_email, c.name AS contact_name"
        " FROM incidents i JOIN users u ON u.id = i.user_id"
        " LEFT JOIN contacts c ON c.user_id = i.user_id"
        " WHERE i.state = 'alerted' ORDER BY i.alerted_at DESC, i.id DESC"
    ).fetchall()
    return jsonify(incidents=[serialize(r) for r in rows])


@bp.route("/api/incidents/<int:incident_id>/status", methods=("POST",))
@admin_only
def update_status(incident_id):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in STATUSES:
        return jsonify(error="Unknown status."), 400
    db = get_db()
    incident = db.execute(
        "SELECT * FROM incidents WHERE id = ? AND state = 'alerted'", (incident_id,)
    ).fetchone()
    if incident is None:
        return jsonify(error="Incident not found."), 404
    db.execute("UPDATE incidents SET status = ? WHERE id = ?", (status, incident_id))
    db.commit()
    flow = current_app.extensions["flow"]
    broker = current_app.extensions["broker"]
    if status == "False alarm":
        flow.send_all_clear(incident)
    broker.publish("admin", "incident", {"id": incident_id, "kind": "update"})
    if not incident["duress"]:
        broker.publish(f"user:{incident['user_id']}", "status", {"id": incident_id, "status": status})
    contact = db.execute("SELECT token FROM contacts WHERE user_id = ?", (incident["user_id"],)).fetchone()
    if contact:
        broker.publish(f"contact:{contact['token']}", "alert", {"id": incident_id})
    return jsonify(status=status)
