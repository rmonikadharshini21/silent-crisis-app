# Test checklist

Updated 2026-11-02. **Auto** = automated test with fake camera and fake email. **Browser** = run in a real browser. **Not run** = still needs doing.

| Story | Criterion | Result | How |
| --- | --- | --- | --- |
| S1 | New account is created | Pass | Auto, Browser |
| S1 | Wrong password does not log in | Pass | Auto |
| S2 | Valid contact is saved and shown | Pass | Auto, Browser |
| S2 | Invalid email shows an error and saves nothing | Pass | Auto |
| S3 | PIN and location are stored; PIN is hashed | Pass | Auto, Browser |
| S3 | Monitoring is blocked until setup is finished | Pass | Auto |
| S4 | Starts only after consent, with an indicator | Partial | Consent: Auto. Live webcam: **not run** |
| S4 | Stop turns the webcam and indicator off | Partial | Auto with fake camera. Live webcam: **not run** |
| S4 | Consent notice covers contact and admin sharing | Pass | Auto, Browser |
| S5 | Staged fall starts the countdown | **Not run** | Rules pass on simulated data only |
| S5 | At most 2 false triggers in 10 normal actions | **Not run** | Rules pass on simulated data only |
| S5 | At least 8 of 10 staged falls detected | **Not run** | Needs the team's staged falls |
| S5 | No video is saved or uploaded | Partial | Auto: no files written. Real camera: **not run** |
| S6 | Fall video starts the countdown; no-fall video does not | **Not run** | Needs sample videos and the pose model |
| S7 | 10-second timer and warning appear | Pass | Browser |
| S7 | Correct PIN: no alert, logged as cancelled | Pass | Auto, Browser |
| S7 | Wrong PIN: countdown continues | Pass | Auto, Browser |
| S8 | Contact gets email within 30 seconds | **Not run** | Wording checked by Auto; no real email sent |
| S8 | Alert says "possible fall, not confirmed", with name, time, location | Pass | Auto |
| S8 | Saved location is used and labelled | Pass | Auto, Browser |
| S8 | If email fails, alert appears on contact page | Pass | Auto, Browser |
| S9 | Non-admin is denied | Pass | Auto |
| S9 | Incident appears as New, live | Pass | Auto, Browser |
| S9 | Details show student, time, source, confidence, location | Pass | Auto, Browser |
| S10 | New status is saved and shown | Pass | Auto, Browser |
| S10 | Status remains after refresh | Pass | Auto, Browser |
| S11 | SOS starts the same flow; source shows SOS | Pass | Auto, Browser |
| S12 | Student sees own incidents only | Pass | Auto |
| S13 | Duress PIN looks cancelled; alert is still sent | Pass | Auto, Browser |
| S14 | Map shows the saved location | Pass | Browser |
| S14 | Nearby police stations and hospitals appear | **Not run** | Search service returned an error; fallback message worked |
| S15 | False alarm tells the contact, once | Pass | Auto, Browser (no real email) |

## Still to do by the team

1. Test with the real webcam while sitting in view. Two 8-second checks got frames and stopped cleanly, but saw no person in any check. The second ran with the user in view. Both last frames were exactly 7,091 bytes, which suggests a blank or blocked image, so pose tracking on a person is still unconfirmed.
2. Stage 10 falls and 10 normal actions, safely, and log the results.
3. Record fall and no-fall videos for `samples/`.
4. Add SMTP settings and time a real email alert.
5. Time a PIN cancel from across the room.
