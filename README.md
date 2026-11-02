# Silent Crisis

A hackathon prototype. A student turns on webcam monitoring; if a fall is detected and nobody cancels within 10 seconds, a trusted contact is alerted with a location, and a campus admin tracks the incident.

It is a warning signal, not a safety guarantee. Accuracy has not been tested in real conditions.

## Run it

Needs Python 3.12 or newer and a webcam. On Windows:

```bash
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\download_model.py
.venv\Scripts\python run.py
```

Open http://127.0.0.1:5000. On first start, the admin account comes from `.env.example`. Copy it to `.env` and change the password before showing this to anyone.

`scripts\download_model.py` fetches the MediaPipe pose model (about 6 MB) from Google. Without it, everything works except fall detection, including the manual SOS.

## Demo flow

1. Sign up, then add a trusted contact, a PIN and a saved location in Setup.
2. On the dashboard, accept the consent notice and start monitoring.
3. Stage a fall safely, onto a mat, or pick a recorded video from `samples/`.
4. Let the countdown finish, then open the contact's private link from Setup.
5. Log in as admin in another browser, and update the incident's status.

## Email alerts

Set `SMTP_*` in `.env`. Gmail needs an app password. Without it, alerts appear on the contact page and the dashboard says so.

The alert page link uses `BASE_URL`. With the default, it only opens on this laptop, but the OpenStreetMap link in the email works anywhere.

## Tests

```bash
.venv\Scripts\python -m pytest
```

These use simulated pose data and a fake camera, so they don't measure real accuracy. Results are in [TEST_CHECKLIST.md](TEST_CHECKLIST.md).

## How it fits together

| Folder | What it holds |
| --- | --- |
| `detection/` | Fall rules, MediaPipe wrapper and the camera thread |
| `app/` | Flask routes, countdown and alert logic, SQLite schema, pages |
| `tests/` | Story-by-story acceptance tests |
| `samples/` | Your recorded test videos (not committed) |

## Known limits

- **One laptop:** the camera is read by Python on the same machine as the server, so one student at a time can be monitored. Hosting it online needs a redesign.
- **HTTP on localhost:** use HTTPS and `COOKIE_SECURE=1` anywhere else. Flask's built-in server is for this demo only.
- **Falls only:** a fall out of view can't be seen. Quickly lying down may trigger the countdown, which is why the PIN exists.
- **Out-of-frame falls:** if a person drops quickly out of the bottom of the frame and stays gone for 3 seconds, it counts as a possible fall. This rule was added for laptop webcams, which often can't see the floor.
- **Nearby help:** this uses public OpenStreetMap services, which can be slow or incomplete.
- **In memory:** live countdown timers and login limits reset on restart. A countdown interrupted by a restart sends its alert on the next start.
