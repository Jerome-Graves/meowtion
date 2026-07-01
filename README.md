<p align="center">
  <img src="docs/hero-banner.png" alt="Meowtion — on-device AI that reads your cat's health from its daily habits" width="820">
</p>

<p align="center">
  <a href="https://meowtion.streamlit.app"><b>🐾 Live dashboard</b></a>
  &nbsp;·&nbsp; <a href="#how-it-works">How it works</a>
  &nbsp;·&nbsp; <a href="#build-your-own">Build your own</a>
  &nbsp;·&nbsp; <a href="#license">License</a>
</p>

<p align="center">
  <a href="https://github.com/Jerome-Graves/meowtion/actions/workflows/test.yml"><img src="https://github.com/Jerome-Graves/meowtion/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/Jerome-Graves/meowtion/actions/workflows/codeql.yml"><img src="https://github.com/Jerome-Graves/meowtion/actions/workflows/codeql.yml/badge.svg" alt="CodeQL"></a>
  <a href="https://codecov.io/gh/Jerome-Graves/meowtion"><img src="https://codecov.io/gh/Jerome-Graves/meowtion/branch/main/graph/badge.svg" alt="coverage"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="license: MIT"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/C-C11-A8B9CC?logo=c&logoColor=black" alt="C">
  <img src="https://img.shields.io/badge/nRF52840-Zephyr%20%2F%20NCS-00A9CE" alt="nRF52840 / Zephyr">
  <img src="https://img.shields.io/badge/ESP32--S3-ESP--IDF-E7352C?logo=espressif&logoColor=white" alt="ESP32-S3 / ESP-IDF">
  <img src="https://img.shields.io/badge/Firebase-RTDB%20%C2%B7%20Functions%20%C2%B7%20Storage-FFCA28?logo=firebase&logoColor=black" alt="Firebase">
  <a href="https://meowtion.streamlit.app"><img src="https://img.shields.io/badge/Streamlit-live%20demo-FF4B4B?logo=streamlit&logoColor=white" alt="Streamlit live demo"></a>
</p>

---

**A smart cat collar that watches your cat's health through its habits.** On-device AI tracks
eating, drinking, activity, rest and purring, surfacing the routine changes that can flag illness
early (cats hide it well). It is trainable to recognise any behaviour, all on a live dashboard.

![A cat wearing the Meowtion collar](hardware/images/photos/cat-wearing-collar.jpg)

## The problem

Cats are experts at hiding illness, so by the time something looks obviously wrong it is often
already advanced. The early warning is in their routine: a cat that suddenly drinks more, eats
less, or stops grooming is telling you something. Meowtion watches those habits continuously, so
you notice the change rather than the crisis.

## How it works

A battery collar senses on the cat and classifies behaviour on the device itself. It relays the
result over Bluetooth to a plugged-in base station, which forwards it to the cloud over WiFi. A
hosted dashboard shows the owner their cat's activity and trends, live.

```text
  Cat
   │
   ▼
  Collar     nRF52840 Sense · Zephyr · on-device AI · battery
   │  BLE
   ▼
  Station    ESP32-S3 · ESP-IDF · Wi-Fi gateway · mains-powered
   │  Wi-Fi / HTTPS
   ▼
  Firebase   Auth · Realtime Database · Cloud Storage · Functions
   │
   ▼
  Dashboard  Streamlit + Firebase web
   │
   ▼
  Owner
```

The collar is Bluetooth-only, so the always-on station is its gateway to the cloud. It is
multi-user: each owner registers their own cats and stations and sees only their own data.

### On-device AI

The collar runs a confidence-gated cascade: a motion (IMU) model always runs, and when it is
unsure a short audio model confirms (eating and drinking look alike by motion, but not by sound).
Both are tiny int8 TensorFlow Lite Micro models. Classification happens on the collar, and raw
audio is processed on-device and discarded, never recorded or transmitted.

### Teach it any behaviour

The pipeline is not hard-coded to a fixed set of actions. You define the behaviours to recognise
in the dashboard (eat, drink, purr, scratch, litter-tray, and so on), label the captured clips,
and the model trains on whatever set you choose. Meowtion is a platform for recognising any pet
behaviour, not a fixed-function gadget.

## Repository

```
meowtion/
├── hardware/     the physical build: parts, 3D-print files, assembly   (hardware/README.md)
├── firmware/     on-device code: collar (nRF52840), station (ESP32-S3)
├── app/          the web app
│   ├── dashboard/  Streamlit + static front end                        (app/dashboard/README.md)
│   └── firebase/   Auth, database, storage, functions, rules           (app/firebase/README.md)
└── docs/         system documentation, incl. the full technical reference (docs/technical/)
```

**Full technical reference** (hardware, firmware, on-device AI, training, cloud, protocols,
security): [`docs/technical/`](docs/technical/) — read the prebuilt
[PDF](docs/technical/meowtion-technical.pdf) or build it from the LaTeX sources.

## Build your own

The hardware is open. Print the enclosure, solder the boards, flash both chips, and point them at
your own Firebase project.

1. **Hardware** (parts, prints, assembly): [`hardware/README.md`](hardware/README.md)
2. **Backend** (create the Firebase project and deploy): [`app/firebase/README.md`](app/firebase/README.md)
3. **Dashboard** (run or host the web app): [`app/dashboard/README.md`](app/dashboard/README.md)
4. **Firmware** (flash the collar and station): [`firmware/collar/README.md`](firmware/collar/README.md), [`firmware/station/README.md`](firmware/station/README.md)

## Tech stack

- **Collar:** Seeed XIAO nRF52840 Sense, Zephyr / nRF Connect SDK, TensorFlow Lite Micro
- **Station:** Seeed XIAO ESP32-S3, ESP-IDF, NimBLE + WiFi
- **Cloud:** Firebase (Auth, Realtime Database, Cloud Storage, Python Cloud Functions)
- **Dashboard:** Streamlit (Python) + Firebase web SDK (JavaScript)
- **Training:** TensorFlow, run server-side in a Cloud Function

## Privacy and security

Data is private per owner: the database and storage rules scope every read and write to the owning
account. Devices carry only a scoped, revocable token, never the owner's password. The microphone
is used only for on-device classification, so raw audio is never stored or transmitted. The web
API key is a public client identifier (safe to ship); no service-account key is in the repo. See
[`app/firebase/README.md`](app/firebase/README.md) for the full model.

## Roadmap

Meowtion runs end to end today. What's next, roughly in priority order:

- **From activity to health insight** — adaptive per-cat baselines, multi-day trend anomaly detection,
  and a concise vet-shareable summary when a habit drifts. This is the core goal: notice the change
  early, and it needs no new hardware.
- **Richer, per-cat recognition** — more behaviours (scratching, litter-tray, grooming, play) and a
  short per-cat fine-tune, both straight out of the label-agnostic pipeline.
- **Longer battery life** — hardware wake-on-motion (an IMU interrupt waking the SoC from deep sleep)
  and tuning the activity gate and audio duty cycle against the measured power budget.
- **Multiple cats, shared stations** — model generalisation across cats, and telling apart two cats
  that share a bowl or station.
- **Full firmware over the air** — today only models are delivered wirelessly; extend the same
  mechanism to complete firmware updates.
- **Field validation and publication** — a larger, multi-household dataset (ideally with vet-confirmed
  events) and a write-up of the confidence-gated cascade.

## License

- **Code** (firmware, app, scripts): [MIT](LICENSE).
- **Hardware** (the designs and 3D-print files in [`hardware/`](hardware/)):
  [CERN-OHL-S v2](hardware/LICENSE), the strongly-reciprocal open-hardware licence.

Copyright (c) 2026 Jerome Graves and Rose Delcour-Min.
