# Security and testing evidence

This document states Meowtion's security controls and its automated testing, with the evidence for
each (source files, enforced rules, CI workflows, and badges). Everything below describes the system
as it stands.

---

## Security

Security is enforced by the backend and the rules, not by the client. The collar holds no
credentials, the station holds only a scoped, revocable token, and every read and write is checked
against per-owner rules.

### Identity and per-owner isolation
Owners authenticate with Firebase Authentication. All of an owner's data lives under
`users/<uid>/`, and the Realtime Database and Cloud Storage rules scope every read and write to the
owning account, so an owner (and that owner's devices) can reach only their own data.
**Evidence:** `app/firebase/database.rules.json`, `app/firebase/storage.rules` (deployed to project
`meowtion-app`).

### Devices use scoped tokens, not credentials
A station authenticates with a per-device token that maps to exactly one owner
(`deviceTokens/<token>/owner`); the collar holds nothing. A token grants access only to that device's
own subtree, and deleting it revokes the device with no password change and no effect on the owner's
other devices. The database rules allow an account to **claim only an unclaimed token or one it
already owns**, so a known token cannot be re-pointed to another account.
**Evidence:** the `deviceTokens` and `users/<uid>/devices/<token>` rules in
`app/firebase/database.rules.json`.

### Storage denies all direct client writes
Training clips (the only sensitive recorded data) are readable only by the owning account and are
never world-readable. Model blobs are public-read so the token-only station can fetch them for
over-the-air delivery. **No client writes to Storage at all**, uploads happen only through the
authenticated `upload_clip` function, which writes as administrator into the owner's area.
**Evidence:** `app/firebase/storage.rules` (training owner-read + `write: false`; models public-read
+ `write: false`; catch-all deny).

### Authenticated, validated clip ingest
`upload_clip` verifies the device token, which it reads from an `Authorization: Bearer` header (kept
out of URLs and request logs). The path segments it interpolates into Storage object names
(`collar`, `ts`) are constrained by regular expressions, which prevents path-traversal and injection,
and the upload body is size-capped.
**Evidence:** `app/firebase/functions/main.py`; the `_SAFE_ID` / `_SAFE_TS` regexes are unit-tested
in `app/firebase/functions/tests/test_helpers.py`.

### Privileged training is gated
Model training (`train`) is restricted to developer accounts, verified server-side from a Firebase
ID token and checked against `config/devAccounts/<uid>`.
**Evidence:** `app/firebase/functions/main.py`.

### Configuration is least-privilege
The `config` subtree is never client-writable. Reads are scoped to only what a client needs:
`config/demoOwner` is public (it backs the read-only demo) and a signed-in user may read only their
own `config/devAccounts/<uid>` flag, so the developer list cannot be enumerated.
**Evidence:** the `config` rules in `app/firebase/database.rules.json`.

### Enforced read-only demo
The public demo reads one designated account whose data the rules make world-readable but
write-locked, so the demo cannot change data or trigger any function. The read-only behaviour holds
even against a hand-crafted client because it is enforced by the rules, not hidden in the UI.
**Evidence:** the `users/<uid>` read rule keyed on `config/demoOwner`.

### Secret handling
No service-account key is present in the repository; the Cloud Functions run on their ambient service
account. Device Wi-Fi credentials are entered at runtime and never committed. The Firebase web API
key in the static front end is a public client identifier (security is enforced by Authentication and
the rules, not by hiding it). `.gitignore` guards against committing any local secret file.
**Evidence:** `.gitignore`; a scan of the tracked files finds no credentials other than the public
web API key.

### Automated security scanning
CodeQL static analysis (GitHub code scanning) runs on every push and pull request; findings surface
in the repository's Security tab. A second-pass scan with Aikido is scheduled for the final phase and
its results will be appended here.
**Evidence:** `.github/workflows/codeql.yml` and the **CodeQL** badge.

---

## Testing

Testing is split deliberately: pure logic is covered by automated unit tests run in CI, and the
integration and on-device behaviour that cannot be unit-tested is verified on the real hardware and
backend.

### Automated unit tests
57 Python unit tests and host-compiled C tests run on every push:

- **Dashboard data layer** (`app/dashboard/tests/`) , raw-event to DataFrame conversion, model-label
  resolution, the low-power-rest (`0xFE`) event handling, activity filtering, the time-window
  drill-down, and the health-watch recent-vs-baseline comparison.
- **Cloud function logic** (`app/firebase/functions/tests/`) , per-window normalisation (the exact
  representation the collar must reproduce at inference), the overlapping-window framing, the WAV
  parser, and the path-validation regexes (a security control).
- **On-device cascade (C)** (`firmware/test/`) , the rules-based activity gate (sustained stillness
  trips low-power rest; motion resets the timer) and the confidence-gated cascade (the audio stage
  runs only when enabled, present, audio exists, and the IMU was unsure; the more-confident stage
  wins).

**Evidence:** the test suites above and the green **tests** badge.

### Coverage
Line coverage of the unit-testable core (`meowtion_dash/data.py` and the pure helpers in the Cloud
Function's `main.py`) is **100%**. The Firebase request handlers, TensorFlow training, the Streamlit
UI, and the hardware-bound firmware paths are excluded from this figure and are verified by the
manual / on-hardware checks below.
**Evidence:** the **coverage** badge (Codecov) and `.coveragerc`.

### Continuous integration
Every push and pull request runs the full Python suite, the C suite, and CodeQL.
**Evidence:** `.github/workflows/test.yml`, `.github/workflows/codeql.yml`; status badges in the
README.

### Manual and on-hardware verification
The integration behaviour was confirmed directly on the collar (XIAO nRF52840 Sense) and station
(ESP32-S3) over USB serial, plus the build and deploy steps:

| # | Area | Condition | Result |
|---|------|-----------|--------|
| 1 | Model delivery | Boot with OTA'd models in flash | Both slots load (23,616 B IMU; 19,640 B audio) |
| 2 | On-device inference | Production mode | Real class + confidence on a full window |
| 3 | Activity gate | Still ~60 s | Enters low-power rest; periodic logging stops |
| 4 | Wake on motion | Move while resting | Wakes and resumes classification |
| 5 | Rest event | Rest then wake | Station logs the span as one `rest` episode |
| 6 | Collar build | `west build` (NCS v3.3.1) | UF2 produced (FLASH 57.6 %, RAM 86.6 %) |
| 7 | Station build | `idf.py build` (ESP-IDF) | Image produced (22 % partition free) |
| 8 | Backend deploy | `firebase deploy` | Rules and functions released to `meowtion-app` |

**Evidence:** `TESTING.md` (full table and run instructions).

### Scope statement
What the automated tests deliberately do not cover, and why: the Firebase request handlers and the
TensorFlow training are integration code (verified by deploy + the table above); the Streamlit UI is
presentation; and the firmware's hardware-bound modules require the on-device checks above rather than
host unit tests. The boundary is recorded in `.coveragerc` and the `# pragma: no cover` markers.
