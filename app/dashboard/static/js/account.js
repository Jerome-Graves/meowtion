/*
 * account.js - Meowtion account page.
 * Authentication (email/password, Google, read-only demo), account management,
 * device pairing over Web Serial, and coarse town-level location for local weather.
 * Loaded after firebase-config.js, the Firebase compat SDKs, and firebase-init.js.
 */

    let isDemo = false;
    let g_demoUid = null;   // the public demo account's uid, set when "View demo" is used
    let locationDetected = false;

    function showView(name) {
      ["login", "signup", "reset", "account"].forEach(v =>
        document.getElementById("view-" + v).classList.toggle("hidden", v !== name));
    }
    function msg(id, text, kind) {
      const el = document.getElementById(id);
      el.textContent = text || "";
      el.className = "msg" + (kind ? " " + kind : "");
    }
    function strongEnough(pw) {
      return pw.length >= 8 && /[A-Za-z]/.test(pw) && /[0-9]/.test(pw);
    }
    // Drop the Firebase token in a same-origin cookie so the Python dashboard reads it.
    function setTokenCookie(token) {
      document.cookie = "mtoken=" + token + "; path=/; SameSite=Strict; Secure";
    }
    function clearTokenCookie() {
      document.cookie = "mtoken=; path=/; max-age=0; SameSite=Strict; Secure";
    }

    async function doLogin() {
      isDemo = false;
      try {
        await firebase.auth().signInWithEmailAndPassword(
          document.getElementById("login-email").value.trim(),
          document.getElementById("login-password").value);
      } catch (e) { msg("login-msg", friendly(e), "err"); }
    }

    async function doGoogle() {
      isDemo = false;
      try { await firebase.auth().signInWithPopup(new firebase.auth.GoogleAuthProvider()); }
      catch (e) { msg("login-msg", friendly(e), "err"); }
    }

    // View the demo: no login. Reads the public demo account's data (rules allow it) and shows
    // everything READ-ONLY , no connect, no edit, no delete. Unlimited concurrent viewers.
    async function doDemo() {
      try {
        const owner = (await firebase.database().ref("config/demoOwner").once("value")).val();
        if (!owner) return msg("login-msg", "The demo isn't set up yet.", "err");
        isDemo = true;
        g_demoUid = owner;
        clearTokenCookie();
        document.cookie = "mdemo=" + owner + "; path=/; SameSite=Strict; Secure";   // tells the dashboard to show the demo read-only
        document.getElementById("who").textContent = "Demo";
        document.getElementById("avatar").textContent = "D";
        document.getElementById("demoTag").classList.remove("hidden");
        document.getElementById("acctSub").classList.add("hidden");
        document.getElementById("verify-banner").classList.add("hidden");
        document.getElementById("connectForm").classList.add("hidden");
        document.getElementById("yourData").classList.add("hidden");
        document.getElementById("devToolsWrap").classList.add("hidden");   // never show dev tools in demo
        attachData(g_demoUid);
        showView("account");
      } catch (e) { msg("login-msg", friendly(e), "err"); }
    }

    async function doSignup() {
      isDemo = false;
      const email = document.getElementById("su-email").value.trim();
      const pw = document.getElementById("su-password").value;
      const confirm = document.getElementById("su-confirm").value;
      if (!document.getElementById("su-consent").checked)
        return msg("su-msg", "Please agree to the Privacy Policy to continue.", "err");
      if (!strongEnough(pw))
        return msg("su-msg", "Password needs 8+ characters with a letter and a number.", "err");
      if (pw !== confirm)
        return msg("su-msg", "Passwords don't match.", "err");
      try {
        const cred = await firebase.auth().createUserWithEmailAndPassword(email, pw);
        // Record consent (GDPR: keep proof of what the user agreed to, and when).
        await firebase.database().ref("users/" + cred.user.uid + "/profile/consent").set({
          agreed: true,
          privacyVersion: window.PRIVACY_VERSION,
          at: firebase.database.ServerValue.TIMESTAMP,
        });
        await cred.user.sendEmailVerification();
        msg("su-msg", "Account created. Check your email to verify your address.", "ok");
      } catch (e) { msg("su-msg", friendly(e), "err"); }
    }

    async function doReset() {
      const email = document.getElementById("reset-email").value.trim();
      try {
        await firebase.auth().sendPasswordResetEmail(email);
        // Always show success (don't reveal whether the email exists).
        msg("reset-msg", "If that email has an account, a reset link is on its way.", "ok");
      } catch (e) {
        if (e.code === "auth/invalid-email") msg("reset-msg", "That doesn't look like a valid email.", "err");
        else msg("reset-msg", "If that email has an account, a reset link is on its way.", "ok");
      }
    }

    async function resendVerify() {
      try { await firebase.auth().currentUser.sendEmailVerification();
        msg("acct-msg", "Verification email sent.", "ok"); }
      catch (e) { msg("acct-msg", friendly(e), "err"); }
    }

    function doLogout() {
      clearTokenCookie();
      document.cookie = "mdemo=; path=/; max-age=0; SameSite=Strict; Secure";
      if (isDemo) { isDemo = false; g_demoUid = null; detachData(); showView("login"); return; }
      firebase.auth().signOut();
    }

    async function downloadData() {
      const u = firebase.auth().currentUser;
      const snap = await firebase.database().ref("users/" + u.uid).once("value");
      const blob = new Blob([JSON.stringify(snap.val() || {}, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "meowtion-my-data.json";
      a.click();
    }

    async function deleteAccount() {
      if (isDemo) return msg("acct-msg", "The demo account can't be deleted.", "err");
      if (!confirm("Delete your account, devices, and all cat data? This cannot be undone.")) return;
      const u = firebase.auth().currentUser;
      try {
        await firebase.database().ref("users/" + u.uid).remove();   // erase their data first
        // TODO (Cloud Function): also clear their /deviceRegistry entries.
        await u.delete();                                           // then the auth account
        clearTokenCookie();
      } catch (e) {
        if (e.code === "auth/requires-recent-login")
          msg("acct-msg", "For security, please log out and back in, then delete again.", "err");
        else msg("acct-msg", friendly(e), "err");
      }
    }

    function friendly(e) {
      const m = {
        "auth/invalid-credential": "Wrong email or password.",
        "auth/wrong-password": "Wrong email or password.",
        "auth/user-not-found": "Wrong email or password.",
        "auth/email-already-in-use": "That email already has an account.",
        "auth/invalid-email": "That doesn't look like a valid email.",
        "auth/too-many-requests": "Too many attempts. Please wait a moment.",
        "auth/popup-closed-by-user": "Sign-in cancelled.",
      };
      return m[e.code] || e.message;
    }

    // ---- Devices (collars + stations under /users/{uid}/devices) ----
    function uid() { return isDemo ? g_demoUid : firebase.auth().currentUser.uid; }
    let devicesRef = null, lastDevices = {}, presenceTimer = null;

    function attachData(id) {
      detachData();
      devicesRef = firebase.database().ref("users/" + id + "/devices");
      devicesRef.on("value", s => { lastDevices = s.val() || {}; renderDevices(lastDevices); });
      // re-render on a timer too, so online/offline flips even when no new data arrives
      presenceTimer = setInterval(() => renderDevices(lastDevices), 10000);
    }
    function detachData() {
      if (devicesRef) devicesRef.off();
      if (presenceTimer) clearInterval(presenceTimer);
      devicesRef = null; presenceTimer = null;
    }

    function pill(text, cls) {
      const s = document.createElement("span");
      s.className = "pill " + cls;
      s.textContent = text;
      return s;
    }
    function typeCell(type) {
      const td = document.createElement("td");
      if (type === "station") td.appendChild(pill("📍 Station", "pill-station"));
      else if (type === "collar") td.appendChild(pill("🐈 Collar", "pill-collar"));
      else td.appendChild(pill("Pending", "pill-muted"));   // device reports its type once connected
      return td;
    }
    // A collar never writes to the cloud directly; its live data is relayed by a station under
    // cats/{collarId}. Find the freshest relayed snapshot so the collar's row can show real
    // battery + connection instead of blanks.
    function collarCurrent(collarId, devices) {
      let best = null;
      Object.values(devices || {}).forEach(s => {
        const c = s && s.type === "station" && s.cats && s.cats[collarId] && s.cats[collarId].current;
        if (c && (!best || (c.ts || 0) > (best.ts || 0))) best = c;
      });
      return best;
    }
    function batteryBar(lvlRaw) {
      const lvl = Math.max(0, Math.min(100, lvlRaw));
      const cls = lvl > 50 ? "bat-ok" : lvl > 20 ? "bat-mid" : "bat-low";
      const wrap = document.createElement("div"); wrap.className = "bat";
      const track = document.createElement("div"); track.className = "bat-track";
      const fill = document.createElement("div"); fill.className = "bat-fill " + cls; fill.style.width = lvl + "%";
      track.appendChild(fill);
      const label = document.createElement("span"); label.className = "bat-label"; label.textContent = lvl + "%";
      wrap.append(track, label);
      return wrap;
    }
    function batteryCell(d, id, devices) {
      const td = document.createElement("td");
      if (d.type === "collar") {   // collar is always battery; level comes from its relayed data
        const cur = collarCurrent(id, devices);
        if (cur && typeof cur.battery === "number") td.appendChild(batteryBar(cur.battery));
        else td.appendChild(pill("Battery", "pill-muted"));
        return td;
      }
      if (d.power === "usb") { td.appendChild(pill("🔌 USB", "pill-muted")); return td; }   // no battery wired
      if (typeof d.battery !== "number") { td.appendChild(pill(d.power === "battery" ? "Battery" : "—", "pill-muted")); return td; }
      td.appendChild(batteryBar(d.battery));
      return td;
    }
    // "Online" = wrote a heartbeat recently. A device can't announce it lost power, so we
    // never trust a stored flag , we check how fresh its last current.ts is.
    function isOnline(d) {
      const ts = d.lastSeen;   // the station heartbeats lastSeen every ~10 s
      return typeof ts === "number" && (Date.now() - ts) < 35000;
    }
    function connCell(d, id, devices) {
      const td = document.createElement("td");
      const wrap = document.createElement("span"); wrap.className = "conn";
      const dot = document.createElement("span");
      const label = document.createElement("span");
      let on;
      if (d.type === "collar") {
        // the collar has no cloud heartbeat (BLE-only); it's "connected" when a station is
        // currently relaying fresh data for it
        const cur = collarCurrent(id, devices);
        on = !!(cur && typeof cur.ts === "number" && (Date.now() - cur.ts) < 35000);
      } else {
        on = isOnline(d);
      }
      dot.className = "dot " + (on ? "dot-on" : "dot-off");
      label.textContent = on ? "Connected" : "Offline";
      wrap.append(dot, label);
      td.appendChild(wrap);
      return td;
    }

    function renderDevices(devices) {
      const body = document.getElementById("devicesBody");
      const ids = Object.keys(devices);
      document.getElementById("noDevices").classList.toggle("hidden", ids.length > 0);
      document.getElementById("devicesTable").classList.toggle("hidden", ids.length === 0);
      body.innerHTML = "";
      ids.forEach(id => {
        const d = devices[id];
        const tr = document.createElement("tr");
        const name = document.createElement("td"); name.className = "name";
        const nm = document.createElement("div"); nm.textContent = d.name || "(unnamed)";
        const did = document.createElement("div"); did.className = "devid";
        did.textContent = "ID " + (id.length > 10 ? id.slice(0, 10) + "…" : id);
        name.append(nm, did);
        tr.append(name, typeCell(d.type), batteryCell(d, id, devices), connCell(d, id, devices));
        const td = document.createElement("td"); td.className = "actions";
        if (!isDemo) {
          const btn = document.createElement("button");
          btn.className = "sm danger"; btn.textContent = "Disconnect";
          btn.onclick = () => disconnectDevice(id, d.name);
          td.appendChild(btn);
        }
        tr.appendChild(td);
        body.appendChild(tr);
      });
      renderSeen(devices);
    }

    function newToken() {
      const a = new Uint8Array(24);
      crypto.getRandomValues(a);
      return [...a].map(b => b.toString(16).padStart(2, "0")).join("");   // 48-char random secret
    }

    // Reuse a board you've already authorized (no chooser); only prompt the very first time.
    async function pickEspPort() {
      const granted = await navigator.serial.getPorts();
      const esp = granted.find(p => (p.getInfo && p.getInfo().usbVendorId) === 0x303a);
      if (esp) return esp;
      return navigator.serial.requestPort({ filters: [{ usbVendorId: 0x303a }] });  // Espressif
    }

    // Token-based pairing over Web Serial:
    //  1. picker is filtered to Espressif boards; we confirm "MEOW> meowtion",
    //  2. mint a random device token, record it under YOUR account (deviceTokens/{T} =
    //     {owner: you}) + a device entry (users/{you}/devices/{T}),
    //  3. hand the device its WiFi + token over USB. The device then writes its data to
    //     users/{you}/devices/{T} with no login , the rule allows it because the token is
    //     registered to you. Deleting the device deletes the token, which revokes it.
    async function connectDevice() {
      const name = document.getElementById("connName").value.trim();
      const ssid = document.getElementById("connSsid").value.trim();
      const pass = document.getElementById("connPass").value;
      if (!name || !ssid) return msg("dev-msg", "Device name and WiFi name are required.", "err");
      if (!("serial" in navigator))
        return msg("dev-msg", "Web Serial needs Chrome or Edge, on a flashed, plugged-in device.", "err");

      let port;
      try {
        port = await pickEspPort();   // auto-reuses a previously-authorized board
        await port.open({ baudRate: 115200 });
        msg("dev-msg", "Looking for a Meowtion device…", "ok");

        const token = newToken();
        let lat, lon;   // coarse weather location for the device, if we have it
        try {
          const loc = (await firebase.database().ref("users/" + uid() + "/profile/location").once("value")).val();
          if (loc) { lat = loc.lat; lon = loc.lon; }
        } catch (e) {}

        const reader = port.readable.getReader();
        const writer = port.writable.getWriter();
        const stop = setTimeout(() => reader.cancel().catch(() => {}), 15000);
        let buf = "", sent = false;
        try {
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += new TextDecoder().decode(value);
            const m = buf.match(/MEOW> meowtion id=(\S+)/);
            if (!sent && m) {
              sent = true;
              // record the token + device under your account (you're authed, so this is allowed)
              await firebase.database().ref("deviceTokens/" + token).set({
                owner: uid(), name, createdAt: firebase.database.ServerValue.TIMESTAMP,
              });
              // seed the station's allow-list with collars already registered to this account,
              // so it relays them straight away (the "2 devices" gate lives in this list)
              const allowedCollars = {};
              Object.keys(lastDevices).forEach(devId => {
                if (lastDevices[devId] && lastDevices[devId].type === "collar") allowedCollars[devId] = true;
              });
              await firebase.database().ref("users/" + uid() + "/devices/" + token).set({
                name, type: "station", online: false, allowedCollars,
              });
              // hand the device its WiFi + token over USB only
              const payload = { ssid, pass, owner: uid(), token, name };
              if (typeof lat === "number") { payload.lat = lat; payload.lon = lon; }
              await writer.write(new TextEncoder().encode(JSON.stringify(payload) + "\n"));
              msg("dev-msg", "Found device (" + m[1] + "). Provisioning…", "ok");
            }
            if (sent && /MEOW> provisioned/.test(buf)) break;
            const em = buf.match(/MEOW> error ([^\r\n]*)/);
            if (sent && em) { msg("dev-msg", "Device error: " + em[1], "err"); break; }
          }
        } catch (e) { /* cancelled / timed out */ }
        clearTimeout(stop);
        try { writer.releaseLock(); } catch (e) {}
        try { reader.releaseLock(); } catch (e) {}

        if (sent) {
          msg("dev-msg", "Device added , it'll come online in the table above shortly.", "ok");
          document.getElementById("connName").value = "";
          document.getElementById("connSsid").value = "";
          document.getElementById("connPass").value = "";
        } else {
          msg("dev-msg", "That port didn't identify as a Meowtion device in setup mode. Flash the firmware and power-cycle the board, then retry.", "err");
        }
      } catch (e) {
        msg("dev-msg", e.message || "Couldn't open the serial port.", "err");
      } finally {
        if (port) { try { await port.close(); } catch (e) {} }
      }
    }

    // Collars are discovered over BLE by the station, which publishes the unregistered ones it
    // hears to devices/{stationToken}/seen. We list them here with a one-tap Register button ,
    // no collar USB needed (the collar's USB serial is unreliable; its BLE link is rock-solid).
    function renderSeen(devices) {
      const wrap = document.getElementById("seenWrap");
      const list = document.getElementById("seenList");
      if (!wrap || !list) return;
      const seen = {};
      Object.values(devices || {}).forEach(d => {
        if (d && d.type === "station" && d.seen) Object.keys(d.seen).forEach(id => { seen[id] = true; });
      });
      // drop any that are already registered as a collar device
      Object.keys(devices || {}).forEach(id => { if (devices[id] && devices[id].type === "collar") delete seen[id]; });
      const ids = Object.keys(seen);
      wrap.classList.toggle("hidden", ids.length === 0 || isDemo);
      list.innerHTML = "";
      ids.forEach(id => {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:.5rem;padding:.45rem .2rem;border-top:1px solid var(--line);";
        const left = document.createElement("div");
        left.innerHTML = '<span class="pill pill-collar">🐈 Collar</span> &nbsp;<span class="devid">' + id + '</span>';
        const btn = document.createElement("button");
        btn.className = "sm primary"; btn.textContent = "Register";
        btn.onclick = async () => {
          const name = (prompt("Name this collar", id) || "").trim() || id;
          btn.disabled = true; btn.textContent = "Registering…";
          try {
            await registerCollar(id, name);
            msg("dev-msg", "Collar " + id + " registered , it'll appear above and report through your station shortly.", "ok");
          } catch (e) {
            btn.disabled = false; btn.textContent = "Register";
            msg("dev-msg", e.message || "Couldn't register the collar.", "err");
          }
        };
        row.append(left, btn);
        list.appendChild(row);
      });
    }

    // Register a collar to this account: a device entry for the table, plus an allow-list entry
    // under every station so the station relays it (cat data only flows once both are registered).
    async function registerCollar(id, name) {
      const u = uid();
      await firebase.database().ref("users/" + u + "/devices/" + id).set({
        name, type: "collar", registeredAt: firebase.database.ServerValue.TIMESTAMP,
      });
      const updates = {};
      Object.keys(lastDevices).forEach(devId => {
        if (lastDevices[devId] && lastDevices[devId].type === "station")
          updates["users/" + u + "/devices/" + devId + "/allowedCollars/" + id] = true;
      });
      if (Object.keys(updates).length) await firebase.database().ref().update(updates);
    }

    async function disconnectDevice(id, name) {
      if (!confirm('Disconnect and remove "' + (name || "this device") + '"?')) return;
      const u = uid();
      const dev = lastDevices[id] || {};
      await firebase.database().ref("users/" + u + "/devices/" + id).remove();
      if (dev.type === "collar") {
        // pull the collar out of every station's allow-list, which revokes relaying it
        const updates = {};
        Object.keys(lastDevices).forEach(devId => {
          if (lastDevices[devId] && lastDevices[devId].type === "station")
            updates["users/" + u + "/devices/" + devId + "/allowedCollars/" + id] = null;
        });
        if (Object.keys(updates).length) await firebase.database().ref().update(updates);
      } else {
        await firebase.database().ref("deviceTokens/" + id).remove();   // revoke the station's token
      }
    }

    // Coarse, town-level location from the connection's IP, for local weather.
    // We never store a precise location: the city centroid is rounded to ~town precision.
    async function detectLocation() {
      if (locationDetected || isDemo) return;
      locationDetected = true;
      const note = document.getElementById("locNote");
      try {
        const j = await (await fetch("https://ipapi.co/json/")).json();
        if (!j || !j.city) return;
        const label = [j.city, j.country_name].filter(Boolean).join(", ");
        if (note) note.textContent = "📍 Local weather will use your town: " + label +
          ". Only the town is stored, never your precise location.";
        const round1 = n => Math.round(n * 10) / 10;   // ~11 km, town-level
        await firebase.database().ref("users/" + uid() + "/profile/location").set({
          label, lat: round1(j.latitude), lon: round1(j.longitude), source: "ip-city",
        });
      } catch (e) { /* keep the default note if the lookup fails */ }
    }

    firebase.auth().onAuthStateChanged(async (user) => {
      if (user) {
        isDemo = false;
        document.cookie = "mdemo=; path=/; max-age=0; SameSite=Strict; Secure";
        setTokenCookie(await user.getIdToken());
        const em = user.email || "Anonymous";
        document.getElementById("who").textContent = em;
        document.getElementById("avatar").textContent = (em[0] || "?");
        document.getElementById("demoTag").classList.add("hidden");
        document.getElementById("acctSub").classList.remove("hidden");
        document.getElementById("verify-banner").classList.toggle("hidden", user.emailVerified);
        document.getElementById("connectForm").classList.remove("hidden");
        document.getElementById("yourData").classList.remove("hidden");
        // reveal the Dev tools button only for designated dev accounts (config/devAccounts/{uid})
        try {
          const isDev = (await firebase.database().ref("config/devAccounts/" + user.uid).once("value")).val() === true;
          document.getElementById("devToolsWrap").classList.toggle("hidden", !isDev);
        } catch (e) {}
        attachData(user.uid);
        detectLocation();
        showView("account");
      } else if (!isDemo) {
        detachData();
        showView("login");
      }
    });
