# Firebase backend

Everything server-side: Authentication, the Realtime Database, Cloud Storage, and the Cloud
Functions. This folder is self-contained , **run `firebase deploy` from here** (`.firebaserc` and
`firebase.json` live here).

```
firebase/
├── .firebaserc            project alias (meowtion-app)
├── firebase.json          deploy config (database, storage, functions)
├── database.rules.json    Realtime Database rules (per-owner access)
├── storage.rules          Storage rules (no client writes; owner-scoped reads)
└── functions/             Python Cloud Functions
    ├── main.py            train + upload_clip
    └── requirements.txt
```

## What Firebase provides

- **Auth** , owner accounts (email/password + Google). The collar and station do **not** log in;
  they use a scoped device token instead.
- **Realtime Database** , the live data: devices, cats, clip metadata, model status, config.
- **Storage** , training audio/IMU clips and the trained `.tflite` models.
- **Cloud Functions** , `train` (server-side model training) and `upload_clip` (authenticated clip
  upload for the token-only station).

## One-time setup (Firebase Console)

1. **Create the project**, then upgrade to the **Blaze** plan (2nd-gen functions need it).
2. **Realtime Database** , create it in **europe-west1**.
3. **Authentication** , enable **Email/Password** (and Google sign-in if you want it).
4. **Storage** , enable it (default bucket).
5. After the dashboard is deployed, add its domain (e.g. `*.streamlit.app`) under
   **Auth → Settings → Authorized domains**.

## Deploy

From this folder:

```
firebase deploy                              # rules + functions
firebase deploy --only "database,storage"    # rules only (quote the list in PowerShell)
firebase deploy --only functions             # functions only
```

Gotchas, all hit once on a fresh project:

- The CLI needs a local **`functions/venv`** to discover the Python functions (gitignored). Create
  it and install the import-time deps: `firebase-functions`, `firebase-admin`, `numpy`
  (TensorFlow is imported lazily, so it isn't needed locally).
- The default **compute service account** may need `roles/cloudbuild.builds.builder` (grant it in
  the Cloud console) for the first function build.
- A function whose first create fails and then only **updates** can end up **private** (Cloud Run
  returns 403 to callers). Give it the **`allUsers` → Cloud Run Invoker** binding. This is safe:
  the functions do their own auth in code, so "unauthenticated at the network layer" just means
  "let the request reach the code, which then authenticates it".

## The two functions

- **`train`** , `POST` with a dev-account Firebase ID token. Reads that user's labelled clips,
  trains an int8 IMU + audio model, uploads them to `models/<uid>/`, and updates
  `users/<uid>/models`. Gated by the Firebase token **and** `config/devAccounts/<uid>`.
- **`upload_clip`** , the station has no login, only a device token, so it cannot satisfy Storage
  rules directly. It POSTs clip bytes here with its token; the function verifies
  `deviceTokens/<token>/owner` and writes the file **as admin** to
  `training/<owner>/<collar>/<ts>.{wav,imu}`. This lets the Storage rules deny all direct client
  writes.

## Security model

- **Database rules** scope every read and write to `/users/{uid}` , owners (and their token-auth
  devices) touch only their own data.
- **Storage rules** allow **no client writes**: clips are written only by `upload_clip` (admin) and
  are readable only by their owning account; models are public-read (so the token-auth station can
  fetch one to push to the collar) and written only by `train`.
- The web **`apiKey` is public/safe** , a client identifier; Auth + the rules are the gate, not
  hiding the key. No service-account key is in the repo; the functions use their ambient service
  account.

## Config nodes

The `config` node is read-only to clients (set these in the Console):

- `config/demoOwner` = `<uid>` , that account becomes the public, read-only **demo**.
- `config/devAccounts/<uid>` = `true` , that account is a **dev/admin** (Dev tools, dev console,
  training).
- `users/<uid>/actions` = `[ ... ]` , the behaviours to recognise (managed from the dev console).
