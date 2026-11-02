"""Countdown, alert and monitoring logic shared by the routes."""
import pathlib
import secrets
import threading
import time
from datetime import datetime, timezone

from .db import get_db, now_iso
from .mailer import send_email
from .security import check_secret

MAX_PIN_ATTEMPTS = 5
LOCATION_FRESH_SECONDS = 300
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".webm"}


def setup_missing(user):
    """Return the setup items a student has not finished."""
    missing = []
    contact = get_db().execute("SELECT id FROM contacts WHERE user_id = ?", (user["id"],)).fetchone()
    if contact is None:
        missing.append("trusted contact")
    if not user["pin_hash"]:
        missing.append("cancel PIN")
    if not user["location_label"]:
        missing.append("saved location")
    return missing


def osm_link(lat, lng):
    if lat is None or lng is None:
        return None
    return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}"


class Flow:
    """Owns live countdowns. The server decides when an alert goes out, not the browser."""

    def __init__(self, app, broker):
        self.app = app
        self.broker = broker
        self._lock = threading.RLock()
        self._active = {}
        self._locations = {}

    def update_location(self, user_id, lat, lng):
        with self._lock:
            self._locations[user_id] = (lat, lng, time.monotonic())

    def clear_location(self, user_id):
        with self._lock:
            self._locations.pop(user_id, None)

    def active_for(self, user_id):
        with self._lock:
            for incident_id, item in self._active.items():
                if item["user_id"] == user_id and not item["duress"]:
                    return {
                        "id": incident_id,
                        "remaining": max(0.0, item["ends"] - time.monotonic()),
                        "trigger": item["trigger"],
                    }
        return None

    def start(self, user_id, trigger, confidence=None):
        """Begin a countdown. Returns the active one if it is already running."""
        with self._lock:
            current = self.active_for(user_id)
            if current:
                return current
            with self.app.app_context():
                db = get_db()
                cursor = db.execute(
                    "INSERT INTO incidents (user_id, trigger_source, confidence, state, started_at, token)"
                    " VALUES (?, ?, ?, 'counting', ?, ?)",
                    (user_id, trigger, confidence, now_iso(), secrets.token_urlsafe(24)),
                )
                db.commit()
                incident_id = cursor.lastrowid
            seconds = self.app.config["COUNTDOWN_SECONDS"]
            timer = threading.Timer(seconds, self._fire, args=(incident_id,))
            timer.daemon = True
            self._active[incident_id] = {
                "user_id": user_id,
                "ends": time.monotonic() + seconds,
                "timer": timer,
                "attempts": 0,
                "trigger": trigger,
                "duress": False,
            }
            timer.start()
        self.broker.publish(f"user:{user_id}", "countdown", {
            "id": incident_id, "remaining": seconds, "trigger": trigger,
        })
        self.app.extensions["monitors"].pause(user_id)
        return {"id": incident_id, "remaining": seconds, "trigger": trigger}

    def cancel(self, incident_id, user_id, pin):
        """Check a PIN. Returns cancelled, wrong_pin, locked or too_late."""
        with self._lock:
            item = self._active.get(incident_id)
            if item is None or item["user_id"] != user_id:
                return "too_late"
            if item["duress"]:
                return "cancelled"
            if item["attempts"] >= MAX_PIN_ATTEMPTS:
                return "locked"
            item["attempts"] += 1
        # bcrypt is slow on purpose, so check outside the lock.
        with self.app.app_context():
            user = get_db().execute(
                "SELECT pin_hash, duress_pin_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        is_pin = check_secret(pin, user["pin_hash"])
        is_duress = not is_pin and check_secret(pin, user["duress_pin_hash"])
        if is_duress:
            with self._lock:
                item = self._active.get(incident_id)
                if item is None:
                    return "too_late"
                item["duress"] = True
                item["timer"].cancel()
            self.broker.publish(f"user:{user_id}", "countdown_end", {"id": incident_id, "outcome": "cancelled"})
            threading.Thread(target=self._fire, args=(incident_id,), daemon=True).start()
            return "cancelled"
        if not is_pin:
            return "wrong_pin"
        with self._lock:
            item = self._active.pop(incident_id, None)
            if item is None:
                return "too_late"
            item["timer"].cancel()
        with self.app.app_context():
            db = get_db()
            db.execute("UPDATE incidents SET state = 'cancelled' WHERE id = ?", (incident_id,))
            db.commit()
        self.broker.publish(f"user:{user_id}", "countdown_end", {"id": incident_id, "outcome": "cancelled"})
        self.app.extensions["monitors"].resume(user_id)
        return "cancelled"

    def _pick_location(self, user):
        with self._lock:
            live = self._locations.get(user["id"])
        if live and time.monotonic() - live[2] <= LOCATION_FRESH_SECONDS:
            return ("Current location", live[0], live[1], "browser")
        return (user["location_label"], user["location_lat"], user["location_lng"], "saved")

    def _fire(self, incident_id):
        with self._lock:
            item = self._active.pop(incident_id, None)
        if item is None:
            return
        with self.app.app_context():
            self.send_alert(incident_id, item["duress"])
        if not item["duress"]:
            self.broker.publish(f"user:{item['user_id']}", "countdown_end", {"id": incident_id, "outcome": "alerted"})
        self.app.extensions["monitors"].resume(item["user_id"])

    def send_alert(self, incident_id, duress=False):
        db = get_db()
        incident = db.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        user = db.execute("SELECT * FROM users WHERE id = ?", (incident["user_id"],)).fetchone()
        contact = db.execute("SELECT * FROM contacts WHERE user_id = ?", (user["id"],)).fetchone()
        label, lat, lng, source = self._pick_location(user)
        alerted_at = now_iso()
        db.execute(
            "UPDATE incidents SET state = 'alerted', status = 'New', duress = ?, alerted_at = ?,"
            " location_label = ?, location_lat = ?, location_lng = ?, location_source = ?,"
            " email_status = 'sending' WHERE id = ?",
            (1 if duress else 0, alerted_at, label, lat, lng, source, incident_id),
        )
        db.commit()
        self.broker.publish("admin", "incident", {"id": incident_id, "kind": "new", "name": user["name"]})
        if contact is None:
            db.execute("UPDATE incidents SET email_status = 'no_contact' WHERE id = ?", (incident_id,))
            db.commit()
            return
        self.broker.publish(f"contact:{contact['token']}", "alert", {"id": incident_id})
        threading.Thread(
            target=self._email_alert,
            args=(incident_id, dict(user), dict(contact), incident["trigger_source"], duress,
                  alerted_at, label, lat, lng, source, incident["token"]),
            daemon=True,
        ).start()

    def _email_alert(self, incident_id, user, contact, trigger, duress, alerted_at, label, lat, lng, source, token):
        with self.app.app_context():
            what = "a manual SOS" if trigger == "SOS" else "a possible fall, not confirmed"
            when = datetime.fromisoformat(alerted_at).astimezone().strftime("%d %b %Y, %H:%M:%S")
            lines = [
                f"{contact['name']},",
                "",
                f"{user['name']} listed you as a trusted contact. The Silent Crisis app reported {what}.",
                "",
                f"Time: {when}",
                f"Location ({'saved by the student' if source == 'saved' else 'from their browser'}): {label}",
            ]
            link = osm_link(lat, lng)
            if link:
                lines.append(f"Map: {link}")
            lines += [f"Alert page: {self.app.config['BASE_URL']}/alert/{token}", ""]
            if duress:
                lines += ["They may be under pressure: the alert was sent using a duress PIN. Do not reply on their phone.", ""]
            lines.append("This is a warning signal, not proof of an emergency. Please try to reach them.")
            subject = f"Safety alert: {what} for {user['name']}"
            status = send_email(contact["email"], subject, "\n".join(lines))
            db = get_db()
            db.execute("UPDATE incidents SET email_status = ? WHERE id = ?", (status, incident_id))
            db.commit()
            self.broker.publish("admin", "incident", {"id": incident_id, "kind": "update"})

    def send_all_clear(self, incident):
        """Tell the contact an alert was a false alarm, once."""
        db = get_db()
        if incident["all_clear_at"]:
            return
        db.execute("UPDATE incidents SET all_clear_at = ? WHERE id = ?", (now_iso(), incident["id"]))
        db.commit()
        row = db.execute(
            "SELECT c.name, c.email, c.token, u.name AS student FROM contacts c"
            " JOIN users u ON u.id = c.user_id WHERE c.user_id = ?",
            (incident["user_id"],),
        ).fetchone()
        if row is None:
            return
        self.broker.publish(f"contact:{row['token']}", "alert", {"id": incident["id"]})
        name, email, student = row["name"], row["email"], row["student"]

        def deliver():
            with self.app.app_context():
                send_email(
                    email,
                    f"All clear: {student}",
                    f"{name},\n\nCampus staff marked the recent alert for {student} as a false alarm.\n",
                )

        threading.Thread(target=deliver, daemon=True).start()

    def recover_stale(self):
        """A restart must not silently lose a countdown that was running."""
        with self.app.app_context():
            db = get_db()
            rows = db.execute("SELECT id FROM incidents WHERE state = 'counting'").fetchall()
            for row in rows:
                self.send_alert(row["id"])


class Monitors:
    """One camera, so at most one running monitor."""

    def __init__(self, app, broker):
        self.app = app
        self.broker = broker
        self._lock = threading.Lock()
        self._user_id = None
        self._monitor = None
        self.factory = self._build

    def sample_files(self):
        folder = pathlib.Path(self.app.config["SAMPLES_DIR"])
        if not folder.exists():
            return []
        return sorted(p.name for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS)

    def _build(self, source, on_fall, on_end):
        from detection.monitor import Monitor
        from detection.pose import PoseEstimator

        estimator = PoseEstimator()
        try:
            return Monitor(source, estimator, on_fall, on_end, self.app.config["CONFIDENCE_THRESHOLD"])
        except Exception:
            estimator.close()
            raise

    def start(self, user_id, source):
        with self._lock:
            if self._monitor and not self._monitor.stopped:
                if self._user_id == user_id:
                    return
                raise RuntimeError("Another student is using the camera on this machine.")
            flow = self.app.extensions["flow"]

            def on_fall(score):
                flow.start(user_id, "AI", score)

            def on_end(reason):
                with self._lock:
                    if self._user_id == user_id:
                        self._monitor = None
                        self._user_id = None
                self.broker.publish(f"user:{user_id}", "monitor", {"running": False, "reason": reason})

            self._monitor = self.factory(source, on_fall, on_end)
            self._user_id = user_id
            self._monitor.start()
        self.broker.publish(f"user:{user_id}", "monitor", {"running": True})

    def stop(self, user_id):
        with self._lock:
            monitor = self._monitor if self._user_id == user_id else None
        if monitor:
            monitor.stop()
            monitor.join(timeout=5)

    def get(self, user_id):
        with self._lock:
            if self._user_id == user_id and self._monitor and not self._monitor.stopped:
                return self._monitor
        return None

    def pause(self, user_id):
        monitor = self.get(user_id)
        if monitor:
            monitor.pause()

    def resume(self, user_id):
        monitor = self.get(user_id)
        if monitor:
            monitor.resume()
