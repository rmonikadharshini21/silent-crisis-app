"""Acceptance tests, named after the backlog stories. Uses a temporary database and a fake camera."""
import re
import threading
import time

import pytest

from app import create_app
from app.db import get_db
from detection.monitor import CameraUnavailable
from detection.pose import ModelMissing

COUNTDOWN = 1.5


class FakeMonitor:
    """Stands in for the camera thread, so tests can trigger a fall directly."""

    is_file = False
    latest_jpeg = b"jpeg"
    person_visible = True

    def __init__(self, on_fall, on_end):
        self.on_fall, self.on_end = on_fall, on_end
        self.stopped = False
        self.paused = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True
        self.on_end("stopped")

    def join(self, timeout=None):
        pass

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


@pytest.fixture
def mails():
    return []


@pytest.fixture
def app(tmp_path, mails):
    def sender(to, subject, body):
        mails.append({"to": to, "subject": subject, "body": body})
        return "sent"

    app = create_app({
        "DATABASE": str(tmp_path / "test.db"),
        "SAMPLES_DIR": str(tmp_path),
        "COUNTDOWN_SECONDS": COUNTDOWN,
        "MAIL_SENDER": sender,
        "ADMIN_EMAIL": "admin@example.test",
        "ADMIN_PASSWORD": "admin-test-pass",
    })
    monitors = app.extensions["monitors"]
    monitors.fake = None

    def factory(source, on_fall, on_end):
        monitors.fake = FakeMonitor(on_fall, on_end)
        return monitors.fake

    monitors.factory = factory
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def post(client, path, form=None, json=None, referer="/login", **kwargs):
    token = csrf(client, referer)
    if json is not None:
        return client.post(path, json=json, headers={"X-CSRF-Token": token}, **kwargs)
    return client.post(path, data={**(form or {}), "csrf_token": token}, **kwargs)


def signup(client, email="asha@example.test", name="Asha"):
    return post(client, "/signup", {"name": name, "email": email, "password": "correct-horse"})


def full_setup(client, duress=None):
    post(client, "/setup/contact", {"name": "Ravi", "email": "ravi@example.test"})
    post(client, "/setup/pin", {"pin": "1234", "duress_pin": duress or ""})
    post(client, "/setup/location", {"label": "Hostel A, room 12", "lat": "11.0", "lng": "78.0"})


def login_admin(app):
    admin = app.test_client()
    post(admin, "/login", {"email": "admin@example.test", "password": "admin-test-pass"})
    return admin


def wait_for(predicate, seconds=6):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def incident(app, incident_id=None):
    with app.app_context():
        db = get_db()
        if incident_id:
            return db.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        return db.execute("SELECT * FROM incidents ORDER BY id DESC").fetchone()


def alerted(app):
    row = incident(app)
    return row is not None and row["state"] == "alerted"


# S1 Sign up and log in
def test_s1_signup_creates_account_and_hashes_password(client, app):
    assert signup(client).status_code == 302
    with app.app_context():
        row = get_db().execute("SELECT * FROM users WHERE email = 'asha@example.test'").fetchone()
    assert row["role"] == "student" and row["password_hash"].startswith("$2")


def test_s1_wrong_password_does_not_log_in(client):
    signup(client)
    post(client, "/logout", referer="/dashboard")
    response = post(client, "/login", {"email": "asha@example.test", "password": "wrong-password"})
    assert response.status_code == 401
    assert client.get("/dashboard").status_code == 302


def test_s1_duplicate_email_and_bad_input_are_rejected(client, app):
    signup(client)
    post(client, "/logout", referer="/dashboard")
    assert signup(client).status_code == 400
    assert post(client, "/signup", {"name": "X", "email": "nope", "password": "correct-horse"}).status_code == 400
    assert post(client, "/signup", {"name": "X", "email": "x@example.test", "password": "short"}).status_code == 400


def test_login_is_rate_limited(client):
    signup(client)
    post(client, "/logout", referer="/dashboard")
    for _ in range(5):
        post(client, "/login", {"email": "asha@example.test", "password": "wrong-password"})
    response = post(client, "/login", {"email": "asha@example.test", "password": "correct-horse"})
    assert response.status_code == 429


def test_post_without_csrf_token_is_rejected(client):
    assert client.post("/login", data={"email": "a@b.co", "password": "x"}).status_code == 400
    signup(client)
    assert client.post("/api/sos", json={}).status_code == 400


# S2 Add a trusted contact
def test_s2_contact_saved_and_shown(client):
    signup(client)
    post(client, "/setup/contact", {"name": "Ravi", "email": "ravi@example.test"})
    assert "ravi@example.test" in client.get("/setup").get_data(as_text=True)


def test_s2_invalid_email_saves_nothing(client, app):
    signup(client)
    post(client, "/setup/contact", {"name": "Ravi", "email": "not-an-email"})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 0


# S3 Set cancel PIN and fallback location
def test_s3_pin_and_location_stored_hashed(client, app):
    signup(client)
    full_setup(client)
    with app.app_context():
        user = get_db().execute("SELECT * FROM users WHERE role = 'student'").fetchone()
    assert user["pin_hash"].startswith("$2") and user["location_label"] == "Hostel A, room 12"


def test_s3_bad_pin_rejected(client, app):
    signup(client)
    post(client, "/setup/pin", {"pin": "12a4"})
    with app.app_context():
        assert get_db().execute("SELECT pin_hash FROM users WHERE role = 'student'").fetchone()[0] is None


def test_s3_monitoring_blocked_until_setup_done(client):
    signup(client)
    response = post(client, "/api/monitor/start", json={"consent": True}, referer="/dashboard")
    assert response.status_code == 409 and "Finish setup" in response.get_json()["error"]


# S4 Start and stop monitoring with consent
def test_s4_consent_is_required(client, app):
    signup(client)
    full_setup(client)
    response = post(client, "/api/monitor/start", json={"consent": False}, referer="/dashboard")
    assert response.status_code == 400
    assert app.extensions["monitors"].fake is None


def test_s4_consent_notice_mentions_data_sharing(client):
    signup(client)
    full_setup(client)
    html = client.get("/dashboard").get_data(as_text=True)
    assert "trusted contact and the campus admin" in html and "not saved" in html


def test_s4_start_then_stop(client, app):
    signup(client)
    full_setup(client)
    assert post(client, "/api/monitor/start", json={"consent": True}, referer="/dashboard").status_code == 200
    assert client.get("/api/state").get_json()["monitoring"] is True
    with app.app_context():
        assert get_db().execute("SELECT consent_at FROM users WHERE role = 'student'").fetchone()[0]
    post(client, "/api/monitor/stop", json={}, referer="/dashboard")
    assert client.get("/api/state").get_json()["monitoring"] is False


def test_s4_camera_and_model_failures_are_reported(client, app):
    signup(client)
    full_setup(client)
    monitors = app.extensions["monitors"]

    def no_camera(*_):
        raise CameraUnavailable("no")

    monitors.factory = no_camera
    assert post(client, "/api/monitor/start", json={"consent": True}, referer="/dashboard").status_code == 503

    def no_model(*_):
        raise ModelMissing("no")

    monitors.factory = no_model
    assert post(client, "/api/monitor/start", json={"consent": True}, referer="/dashboard").status_code == 503


# S6 Run detection on a recorded video: only files in the samples folder are accepted.
def test_s6_rejects_unknown_or_traversal_source(client):
    signup(client)
    full_setup(client)
    for source in ("../secret.mp4", "missing.mp4"):
        response = post(client, "/api/monitor/start", json={"consent": True, "source": source}, referer="/dashboard")
        assert response.status_code == 400


def test_s6_sample_file_accepted(client, app, tmp_path):
    (tmp_path / "fall.mp4").write_bytes(b"x")
    signup(client)
    full_setup(client)
    response = post(client, "/api/monitor/start", json={"consent": True, "source": "fall.mp4"}, referer="/dashboard")
    assert response.status_code == 200


# S5 and S7: a detected fall starts the countdown; the correct PIN cancels.
def start_fall(client, app):
    post(client, "/api/monitor/start", json={"consent": True}, referer="/dashboard")
    app.extensions["monitors"].fake.on_fall(0.8)
    return client.get("/api/state").get_json()["countdown"]


def test_s5_fall_starts_countdown_and_pauses_detection(client, app):
    signup(client)
    full_setup(client)
    countdown = start_fall(client, app)
    assert countdown and countdown["trigger"] == "AI"
    assert app.extensions["monitors"].fake.paused
    post(client, f"/api/incidents/{countdown['id']}/cancel", json={"pin": "1234"}, referer="/dashboard")


def test_s7_correct_pin_cancels_and_no_alert_is_sent(client, app, mails):
    signup(client)
    full_setup(client)
    countdown = start_fall(client, app)
    token = csrf(client, "/dashboard")
    result = client.post(f"/api/incidents/{countdown['id']}/cancel", json={"pin": "1234"}, headers={"X-CSRF-Token": token})
    assert result.get_json()["result"] == "cancelled"
    time.sleep(COUNTDOWN + 0.3)
    assert incident(app)["state"] == "cancelled" and mails == []
    assert not app.extensions["monitors"].fake.paused


def test_s7_wrong_pin_does_not_stop_countdown(client, app, mails):
    signup(client)
    full_setup(client)
    countdown = start_fall(client, app)
    token = csrf(client, "/dashboard")
    result = client.post(f"/api/incidents/{countdown['id']}/cancel", json={"pin": "9999"}, headers={"X-CSRF-Token": token})
    assert result.get_json()["result"] == "wrong_pin"
    assert wait_for(lambda: alerted(app) and mails)


def test_s7_another_student_cannot_cancel(client, app):
    signup(client)
    full_setup(client)
    countdown = start_fall(client, app)
    other = app.test_client()
    signup(other, "other@example.test", "Other")
    post(other, "/setup/pin", {"pin": "1234"})
    token = csrf(other, "/dashboard")
    result = other.post(f"/api/incidents/{countdown['id']}/cancel", json={"pin": "1234"}, headers={"X-CSRF-Token": token})
    assert result.get_json()["result"] == "too_late"
    assert wait_for(lambda: alerted(app))


# S8 Alert the contact with a location link
def test_s8_alert_email_has_wording_and_location(client, app, mails):
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: mails)
    mail = mails[0]
    assert mail["to"] == "ravi@example.test"
    assert "possible fall, not confirmed" in mail["subject"]
    assert "Asha" in mail["body"] and "Hostel A, room 12" in mail["body"]
    assert "openstreetmap.org" in mail["body"] and "/alert/" in mail["body"]


def test_s8_browser_location_used_when_available(client, app):
    signup(client)
    full_setup(client)
    post(client, "/api/location", json={"lat": 12.5, "lng": 79.5}, referer="/dashboard")
    start_fall(client, app)
    assert wait_for(lambda: alerted(app))
    row = incident(app)
    assert row["location_lat"] == 12.5 and row["location_source"] == "browser"


def test_s8_saved_location_used_and_labelled(client, app):
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: alerted(app))
    row = incident(app)
    assert row["location_source"] == "saved"
    assert "Saved location" in app.test_client().get(f"/alert/{row['token']}").get_data(as_text=True)


def test_s8_failed_email_still_shows_on_contact_page(client, app):
    app.config["MAIL_SENDER"] = lambda *_: "failed"
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: incident(app) and incident(app)["email_status"] == "failed")
    with app.app_context():
        token = get_db().execute("SELECT token FROM contacts").fetchone()[0]
    page = app.test_client().get(f"/c/{token}").get_data(as_text=True)
    assert "Possible fall, not confirmed" in page


def test_s8_contact_links_need_valid_token(client):
    assert client.get("/c/not-a-token").status_code == 404
    assert client.get("/alert/not-a-token").status_code == 404


def test_cancelled_incident_is_not_visible_by_alert_link(client, app):
    signup(client)
    full_setup(client)
    countdown = start_fall(client, app)
    post(client, f"/api/incidents/{countdown['id']}/cancel", json={"pin": "1234"}, referer="/dashboard")
    assert client.get(f"/alert/{incident(app)['token']}").status_code == 404


# S9 See incidents on the dashboard
def test_s9_non_admin_denied(client):
    assert client.get("/admin").status_code == 302
    assert client.get("/admin/api/incidents").status_code == 401
    signup(client)
    assert client.get("/admin").status_code == 403
    assert client.get("/admin/api/incidents").status_code == 403


def test_s9_alerted_incident_listed_with_details(client, app):
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: alerted(app))
    data = login_admin(app).get("/admin/api/incidents").get_json()["incidents"]
    assert len(data) == 1
    item = data[0]
    assert (item["student"], item["status"], item["trigger"], item["confidence"]) == ("Asha", "New", "AI", 0.8)
    assert "openstreetmap" in item["map_link"]


def test_s9_cancelled_incident_not_listed(client, app):
    signup(client)
    full_setup(client)
    countdown = start_fall(client, app)
    post(client, f"/api/incidents/{countdown['id']}/cancel", json={"pin": "1234"}, referer="/dashboard")
    assert login_admin(app).get("/admin/api/incidents").get_json()["incidents"] == []


def test_s9_live_event_reaches_admin_channel(client, app):
    q = app.extensions["broker"].subscribe("admin")
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert "event: incident" in q.get(timeout=3)


# S10 Update incident status
def set_status(app, admin, incident_id, status):
    token = csrf(admin, "/admin")
    return admin.post(f"/admin/api/incidents/{incident_id}/status", json={"status": status}, headers={"X-CSRF-Token": token})


def test_s10_status_saved_and_persists(client, app):
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: alerted(app))
    admin = login_admin(app)
    for status in ("Acknowledged", "Help sent", "Resolved"):
        assert set_status(app, admin, incident(app)["id"], status).status_code == 200
        assert admin.get("/admin/api/incidents").get_json()["incidents"][0]["status"] == status


def test_s10_invalid_status_rejected(client, app):
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: alerted(app))
    assert set_status(app, login_admin(app), incident(app)["id"], "Deleted").status_code == 400


def test_s10_student_cannot_change_status(client, app):
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: alerted(app))
    token = csrf(client, "/dashboard")
    response = client.post(f"/admin/api/incidents/{incident(app)['id']}/status", json={"status": "Resolved"}, headers={"X-CSRF-Token": token})
    assert response.status_code == 403


# S11 Manual SOS
def test_s11_sos_starts_same_flow_with_sos_source(client, app, mails):
    signup(client)
    full_setup(client)
    assert post(client, "/api/sos", json={}, referer="/dashboard").get_json()["trigger"] == "SOS"
    assert wait_for(lambda: alerted(app) and mails)
    assert login_admin(app).get("/admin/api/incidents").get_json()["incidents"][0]["trigger"] == "SOS"


def test_s11_second_press_does_not_start_another_countdown(client, app):
    signup(client)
    full_setup(client)
    first = post(client, "/api/sos", json={}, referer="/dashboard").get_json()
    second = post(client, "/api/sos", json={}, referer="/dashboard").get_json()
    assert first["id"] == second["id"]
    assert wait_for(lambda: alerted(app))


def test_s11_sos_needs_setup(client):
    signup(client)
    assert post(client, "/api/sos", json={}, referer="/dashboard").status_code == 409


# S12 Incident history
def test_s12_history_shows_own_incidents_only(client, app):
    signup(client)
    full_setup(client)
    post(client, "/api/sos", json={}, referer="/dashboard")
    assert wait_for(lambda: alerted(app))
    assert "Manual SOS" in client.get("/history").get_data(as_text=True)
    other = app.test_client()
    signup(other, "other@example.test", "Other")
    assert "Manual SOS" not in other.get("/history").get_data(as_text=True)


# S13 Duress PIN
def test_s13_duress_looks_cancelled_but_alert_is_sent(client, app, mails):
    signup(client)
    full_setup(client, duress="4321")
    countdown = post(client, "/api/sos", json={}, referer="/dashboard").get_json()
    token = csrf(client, "/dashboard")
    result = client.post(f"/api/incidents/{countdown['id']}/cancel", json={"pin": "4321"}, headers={"X-CSRF-Token": token})
    assert result.get_json()["result"] == "cancelled"
    assert client.get("/api/state").get_json()["countdown"] is None
    assert wait_for(lambda: alerted(app) and mails)
    assert "duress" in mails[0]["body"]
    assert incident(app)["duress"] == 1
    assert "Cancelled" in client.get("/history").get_data(as_text=True)
    assert login_admin(app).get("/admin/api/incidents").get_json()["incidents"][0]["duress"] is True


def test_s13_duress_must_differ_from_pin(client, app):
    signup(client)
    post(client, "/setup/pin", {"pin": "1111", "duress_pin": "1111"})
    with app.app_context():
        assert get_db().execute("SELECT pin_hash FROM users WHERE role = 'student'").fetchone()[0] is None


# S14 Nearby help map
def test_s14_map_page_uses_saved_location(client):
    signup(client)
    full_setup(client)
    html = client.get("/help-map").get_data(as_text=True)
    assert 'data-lat="11.0"' in html and "help_map.js" in html


# S15 All clear
def test_s15_false_alarm_sends_all_clear_once(client, app, mails):
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: alerted(app) and mails)
    admin = login_admin(app)
    incident_id = incident(app)["id"]
    set_status(app, admin, incident_id, "False alarm")
    assert wait_for(lambda: any("All clear" in m["subject"] for m in mails))
    set_status(app, admin, incident_id, "False alarm")
    time.sleep(0.2)
    assert sum("All clear" in m["subject"] for m in mails) == 1
    assert "All clear" in app.test_client().get(f"/alert/{incident(app)['token']}").get_data(as_text=True)


def test_s15_other_statuses_send_no_all_clear(client, app, mails):
    signup(client)
    full_setup(client)
    start_fall(client, app)
    assert wait_for(lambda: alerted(app) and mails)
    admin = login_admin(app)
    set_status(app, admin, incident(app)["id"], "Resolved")
    time.sleep(0.2)
    assert not any("All clear" in m["subject"] for m in mails)


# Security and resilience
def test_security_headers_and_cookie_flags(client):
    response = client.get("/")
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    signup(client)
    login = post(client, "/logout", referer="/dashboard")
    cookie = login.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie or cookie == ""


def test_name_is_escaped_in_html(client, app):
    signup(client, name="<script>alert(1)</script>")
    assert "<script>alert(1)" not in client.get("/dashboard").get_data(as_text=True)


def test_interrupted_countdown_is_sent_after_restart(tmp_path, mails):
    def sender(to, subject, body):
        mails.append(to)
        return "sent"

    config = {"DATABASE": str(tmp_path / "r.db"), "COUNTDOWN_SECONDS": 30, "MAIL_SENDER": sender,
              "ADMIN_EMAIL": "admin@example.test", "ADMIN_PASSWORD": "admin-test-pass"}
    first = create_app(config)
    client = first.test_client()
    signup(client)
    full_setup(client)
    active = post(client, "/api/sos", json={}, referer="/dashboard").get_json()
    first.extensions["flow"]._active[active["id"]]["timer"].cancel()
    create_app(config)
    assert wait_for(lambda: mails == ["ravi@example.test"])


def test_concurrent_sos_makes_one_incident(client, app):
    signup(client)
    full_setup(client)
    with app.app_context():
        user_id = get_db().execute("SELECT id FROM users WHERE role = 'student'").fetchone()[0]
    flow = app.extensions["flow"]
    threads = [threading.Thread(target=flow.start, args=(user_id, "SOS")) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 1
    assert wait_for(lambda: alerted(app))
