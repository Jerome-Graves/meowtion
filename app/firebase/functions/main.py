"""
Meowtion Cloud Functions (2nd gen, Python). Two endpoints:

  train       - server-side model training. POST with a dev-account Firebase ID token; reads that
                user's labelled clips from RTDB + Storage, trains a small int8 1-D CNN for each
                cascade stage, uploads the .tflite models to Storage under models/<uid>/, and bumps
                users/<uid>/models/{version,status,results} in RTDB.

  upload_clip - authenticated clip upload for the station. The station has no Firebase login, only a
                device token, so it cannot satisfy Storage rules directly. It POSTs the raw clip
                bytes here with its token; we verify the token maps to an owner
                (deviceTokens/<token>/owner) and write the file as admin to that owner's training
                area. This lets Storage rules deny ALL direct client writes while still allowing the
                token-auth station to upload. Storage layout is owner-scoped:
                    training/<owner-uid>/<collar>/<ts>.{wav,imu}
                which lets the Storage rules grant read only to the owning account.

Both run on the function's ambient service account; NO key file is checked in, so this stays clear of
the "no service-account key in firmware/dashboard" rule (this is neither).

Deploy:  firebase deploy --only functions      (run from app/firebase/)
"""
import json
import re
import struct

import numpy as np
from firebase_functions import https_fn, options
from firebase_admin import initialize_app, db, storage, auth

DB_URL = "https://meowtion-app-default-rtdb.europe-west1.firebasedatabase.app"
BUCKET = "meowtion-app.firebasestorage.app"
REGION = "europe-west1"
initialize_app(options={"databaseURL": DB_URL, "storageBucket": BUCKET})

LABELS = []   # discovered from the labelled data at runtime (any pet action); recorded in RTDB metadata
IMU_RATE, IMU_AXES = 104, 6
IMU_WIN, IMU_HOP = IMU_RATE, IMU_RATE // 2
AUDIO_RATE, AUDIO_WIN, AUDIO_HOP = 8000, 8000, 4000

# Storage path segments are interpolated into object names, so constrain them to safe characters to
# prevent path traversal / injection.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_SAFE_TS = re.compile(r"^[0-9]+$")


def ref(path):
    return db.reference(path, url=DB_URL)


# ======================== upload_clip (station, device-token auth) ========================
@https_fn.on_request(region=REGION, memory=options.MemoryOption.MB_256, timeout_sec=120,
                     cors=options.CorsOptions(cors_origins=["*"], cors_methods=["post", "options"]))
def upload_clip(req: https_fn.Request) -> https_fn.Response:
    token = req.args.get("token", "")
    collar = req.args.get("collar", "")
    ts = req.args.get("ts", "")
    ext = req.args.get("ext", "wav")
    if ext not in ("wav", "imu") or not _SAFE_ID.match(collar) or not _SAFE_TS.match(ts):
        return https_fn.Response("bad collar/ts/ext", status=400)
    # the device token is the station's capability; it maps to exactly one owner account
    owner = ref(f"deviceTokens/{token}/owner").get() if token else None
    if not owner:
        return https_fn.Response("unauthorized", status=401)
    data = req.get_data()
    if not data:
        return https_fn.Response("empty body", status=400)
    ctype = "audio/wav" if ext == "wav" else "application/octet-stream"
    path = f"training/{owner}/{collar}/{ts}.{ext}"
    storage.bucket().blob(path).upload_from_string(data, content_type=ctype)
    return https_fn.Response(json.dumps({"ok": True, "path": path}), status=200,
                             headers={"Content-Type": "application/json"})


# ======================== training ========================
def parse_wav(buf):
    if buf[:4] != b"RIFF" or buf[8:12] != b"WAVE":
        raise ValueError("not a WAV")
    pos, rate, data = 12, 8000, None
    while pos + 8 <= len(buf):
        cid, sz = buf[pos:pos + 4], struct.unpack_from("<I", buf, pos + 4)[0]
        body = pos + 8
        if cid == b"fmt ":
            rate = struct.unpack_from("<I", buf, body + 4)[0]
        elif cid == b"data":
            data = buf[body:body + sz]
        pos = body + sz + (sz & 1)
    if data is None:
        raise ValueError("no data chunk")
    return np.frombuffer(data, dtype="<i2").copy(), rate


def load_clips(uid):
    bucket = storage.bucket()
    devs = ref(f"users/{uid}/devices").get() or {}
    clips = []
    for token, dev in devs.items():
        if not isinstance(dev, dict) or dev.get("type") != "station":
            continue
        for ts, clip in (dev.get("clips") or {}).items():
            label, collar = clip.get("label"), clip.get("collar")
            if not label or not collar:
                continue
            try:
                # owner-scoped Storage layout: training/<uid>/<collar>/<ts>.{wav,imu}
                audio, rate = parse_wav(bucket.blob(f"training/{uid}/{collar}/{ts}.wav").download_as_bytes())
                imu = np.zeros((0, IMU_AXES), np.int16)
                axes = int(clip.get("imuAxes", IMU_AXES))
                imu_blob = bucket.blob(f"training/{uid}/{collar}/{ts}.imu")
                if imu_blob.exists():
                    raw = np.frombuffer(imu_blob.download_as_bytes(), dtype="<i2")
                    imu = raw[:(len(raw) // axes) * axes].reshape(-1, axes)
                a0, a1 = clip.get("trimStartMs"), clip.get("trimEndMs")
                if isinstance(a0, (int, float)):
                    s = int(a0 * rate / 1000)
                    e = int(a1 * rate / 1000) if isinstance(a1, (int, float)) else len(audio)
                    audio = audio[max(0, s):min(len(audio), e)]
                    if len(imu):
                        ir = int(clip.get("imuRateHz", IMU_RATE))
                        e1 = a1 if isinstance(a1, (int, float)) else 1e12
                        imu = imu[max(0, int(a0 * ir / 1000)):min(len(imu), int(e1 * ir / 1000))]
                clips.append({"label": label, "audio": audio, "imu": imu})
            except Exception as ex:
                print(f"skip {ts}: {ex}")
    return clips


def per_window_norm(x):
    x = x.astype(np.float32)
    x -= x.mean(axis=0, keepdims=True)
    return x / (np.max(np.abs(x)) + 1e-6)


def windows(arr, win, hop):
    if len(arr) < win:
        pad = np.zeros((win - len(arr),) + arr.shape[1:], dtype=arr.dtype)
        yield np.concatenate([arr, pad], axis=0)
        return
    for s in range(0, len(arr) - win + 1, hop):
        yield arr[s:s + win]


def build_dataset(clips, kind):
    X, y = [], []
    for c in clips:
        if kind == "imu":
            src = c["imu"]
            if src.shape[0] == 0:
                continue
            win, hop, shape = IMU_WIN, IMU_HOP, (IMU_WIN, IMU_AXES)
        else:
            src = c["audio"].reshape(-1, 1)
            win, hop, shape = AUDIO_WIN, AUDIO_HOP, (AUDIO_WIN, 1)
        for w in windows(src, win, hop):
            X.append(per_window_norm(w).reshape(shape))
            y.append(LABELS.index(c["label"]))
    return np.array(X, np.float32), np.array(y, np.int64)


def train_one(name, clips):
    import tensorflow as tf
    from sklearn.model_selection import train_test_split
    L = tf.keras.layers
    X, y = build_dataset(clips, name)
    if len(X) < 30 or len(np.unique(y)) < 2:
        return None
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, stratify=y, random_state=0)
    if name == "imu":
        model = tf.keras.Sequential([L.Input(X.shape[1:]),
            L.Conv1D(16, 5, padding="same", activation="relu"), L.MaxPool1D(2),
            L.Conv1D(32, 5, padding="same", activation="relu"), L.MaxPool1D(2),
            L.Conv1D(64, 3, padding="same", activation="relu"), L.GlobalAveragePooling1D(),
            L.Dense(32, activation="relu"), L.Dropout(0.3), L.Dense(len(LABELS), activation="softmax")])
    else:
        model = tf.keras.Sequential([L.Input(X.shape[1:]),
            L.Conv1D(8, 9, strides=4, padding="same", activation="relu"),
            L.Conv1D(16, 9, strides=4, padding="same", activation="relu"),
            L.Conv1D(32, 5, strides=2, padding="same", activation="relu"),
            L.Conv1D(32, 3, strides=2, padding="same", activation="relu"),
            L.GlobalAveragePooling1D(), L.Dense(32, activation="relu"), L.Dropout(0.3),
            L.Dense(len(LABELS), activation="softmax")])
    model.compile(optimizer="adam", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(Xtr, ytr, validation_data=(Xte, yte), epochs=40, batch_size=32, verbose=0)
    acc = float((model.predict(Xte, verbose=0).argmax(1) == yte).mean())

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = lambda: ([Xtr[i:i + 1]] for i in range(min(200, len(Xtr))))
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = conv.inference_output_type = tf.int8
    tfl = conv.convert()
    scale, zp = tf.lite.Interpreter(model_content=tfl).get_input_details()[0]["quantization"]
    return {"tflite": bytes(tfl), "windows": int(len(X)), "test_acc": acc,
            "in_scale": float(scale), "in_zp": int(zp)}


@https_fn.on_request(region=REGION, memory=options.MemoryOption.GB_4, timeout_sec=3600,
                     cpu=2, concurrency=1,
                     cors=options.CorsOptions(cors_origins=["*"], cors_methods=["post", "options"]))
def train(req: https_fn.Request) -> https_fn.Response:
    # auth: must be a signed-in dev account (same gate as the dashboard)
    authz = req.headers.get("Authorization", "")
    token = authz.split("Bearer ", 1)[1] if "Bearer " in authz else ""
    try:
        uid = auth.verify_id_token(token)["uid"]
    except Exception:
        return https_fn.Response("unauthorized", status=401)
    if ref(f"config/devAccounts/{uid}").get() is not True:
        return https_fn.Response("not a dev account", status=403)

    ref(f"users/{uid}/models/status").set("training")
    try:
        clips = load_clips(uid)
        if not clips:
            ref(f"users/{uid}/models/status").set("no-data")
            return https_fn.Response("no labelled clips", status=200)
        global LABELS
        LABELS = sorted({c["label"] for c in clips if c.get("label")})   # classes from the data
        if len(LABELS) < 2:
            ref(f"users/{uid}/models/status").set("not-enough-classes")
            return https_fn.Response(f"need >=2 action classes, found {LABELS}", status=200)

        bucket = storage.bucket()
        results = {}
        for name in ("imu", "audio"):
            r = train_one(name, clips)
            if not r:
                continue
            blob = bucket.blob(f"models/{uid}/{name}_model.tflite")
            blob.upload_from_string(r["tflite"], content_type="application/octet-stream")
            results[name] = {k: r[k] for k in ("windows", "test_acc", "in_scale", "in_zp")}
            results[name]["bytes"] = len(r["tflite"])

        if not results:
            ref(f"users/{uid}/models/status").set("not-enough-data")
            return https_fn.Response("not enough data to train any stage", status=200)

        version = int(ref(f"users/{uid}/models/version").get() or 0) + 1
        ref(f"users/{uid}/models").update({"version": version, "status": "ready",
                                           "labels": LABELS, "results": results})

        # Mirror the version into each of this owner's station device configs. The station has only a
        # device token (no Firebase login), so the DB rules let it read ONLY its own
        # users/<uid>/devices/<token>/ subtree, not users/<uid>/models above it. Putting modelVer in
        # the device config is how the station learns a new model is ready: it compares this to its
        # stored copy and, when it increases, downloads models/<uid>/<name>_model.tflite and pushes
        # them to the collar over BLE OTA.
        for tok, dev in (ref(f"users/{uid}/devices").get() or {}).items():
            if isinstance(dev, dict) and dev.get("type") == "station":
                ref(f"users/{uid}/devices/{tok}/config/modelVer").set(version)

        return https_fn.Response(json.dumps({"version": version, "labels": LABELS, "results": results}), status=200)
    except Exception as ex:
        ref(f"users/{uid}/models").update({"status": "error", "error": str(ex)})
        return https_fn.Response(f"error: {ex}", status=500)


# Simulated companion collar ("Purrminator"): a scheduled history generator + manual trigger.
# Imported here so the Firebase CLI discovers `simulate` and `simulate_now` in main's namespace.
from simulator import simulate, simulate_now  # noqa: E402,F401
