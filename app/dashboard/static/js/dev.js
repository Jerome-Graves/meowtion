/*
 * dev.js - Meowtion developer console (dev-account gated).
 * Live station status, capture and mode toggles, the action set, cloud retraining,
 * and clip review (waveform, trim, delete).
 * Loaded after firebase-config.js, the Firebase compat SDKs, and firebase-init.js.
 */

    let g_uid = null;
    const g_demo = new URLSearchParams(location.search).has("demo");   // ?demo=1 => public read-only showcase
    let g_actions = ["eat", "drink", "resting", "moving"];   // default action set; overridden by users/<uid>/actions
    let devicesRef = null, modelsRef = null, actionsRef = null, lastDevices = {}, timer = null, lastClipsSig = "";
    let clipEls = {};   // clip id -> {row}; tracks rows already drawn so renderClips only adds/removes, never rebuilds

    function show(which) {
      document.getElementById("gate").classList.toggle("hidden", which !== "gate");
      document.getElementById("devview").classList.toggle("hidden", which !== "dev");
      if (which === "dev") { installHelpTooltips(); installCardCollapse(); }
    }

    // Make each card collapsible: click the title to open/close. Cards start collapsed, so the
    // console opens as a thin list of titles. Idempotent, so re-running it does nothing.
    function installCardCollapse() {
      document.querySelectorAll("#devview > .card").forEach(card => {
        if (card.dataset.collapsible) return;
        const h = card.querySelector("h3");
        if (!h) return;
        card.dataset.collapsible = "1";
        // header row = the direct child of the card that holds the h3 (h3 itself, or its flex wrapper)
        let header = h;
        while (header.parentElement && header.parentElement !== card) header = header.parentElement;
        // move everything after the header row into a collapsible body
        const body = el("div", "card-body");
        let node = header.nextSibling;
        while (node) { const nx = node.nextSibling; body.appendChild(node); node = nx; }
        card.appendChild(body);
        header.classList.add("card-header");
        h.insertBefore(el("span", "card-chev", "▸"), h.firstChild);
        card.classList.add("collapsible", "collapsed");
        header.addEventListener("click", e => {
          if (e.target.closest("button, a, input, select, .help")) return;   // let header controls work
          const collapsed = card.classList.toggle("collapsed");
          h.querySelector(".card-chev").textContent = collapsed ? "▸" : "▾";
        });
      });
    }

    // Tidy the cards: move each card's description paragraph into a "?" help icon next to the
    // title, shown as a hover/focus popover. Idempotent, so calling it again does nothing.
    function installHelpTooltips() {
      document.querySelectorAll("#devview .card").forEach(card => {
        const h = card.querySelector("h3");
        if (!h || h.querySelector(".help")) return;
        const hint = card.querySelector(".hint");   // the first .hint is the card's description
        if (!hint) return;
        const help = el("span", "help");
        help.tabIndex = 0;
        help.setAttribute("role", "button");
        help.setAttribute("aria-label", "Help");
        const pop = el("span", "help-pop");
        pop.innerHTML = hint.innerHTML;
        help.appendChild(document.createTextNode("?"));
        help.appendChild(pop);
        h.appendChild(document.createTextNode(" "));
        h.appendChild(help);
        hint.remove();
      });
    }
    function fresh(ts) { return typeof ts === "number" && (Date.now() - ts) < 35000; }
    function el(tag, cls, txt) { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }

    // collar battery: prefer a live value the station reports during capture (dev.collarBattery),
    // else fall back to the freshest battery from the collars this station relays (cats/{id}/current)
    function collarBattery(d) {
      if (d.dev && typeof d.dev.collarBattery === "number") return d.dev.collarBattery;
      let best = null;
      if (d.cats) Object.values(d.cats).forEach(cat => {
        const cur = cat && cat.current;
        if (cur && typeof cur.battery === "number" && (!best || (cur.ts || 0) > (best.ts || 0))) best = cur;
      });
      return best ? best.battery : null;
    }

    // ---- single source of truth: is a station hearing a collar, and how close? ----
    // EVERY "connected" indicator derives from this (the station-card badge AND the record gate), so
    // the two can never disagree. It fuses the live proximity report (d.dev: the in-range RSSI gate)
    // with the relayed collar telemetry (d.cats/{id}/current, which the station writes ONLY while it
    // hears that collar). Either being live means the collar is reachable to record right now.
    //   status: "recording" | "inRange" | "approaching" | "near" | "away"   (present = not "away")
    function collarPresence(d) {
      const dev = (d && d.dev) || {};
      let relaying = false, name = dev.nearCollar || null;
      if (d && d.cats) Object.entries(d.cats).forEach(([id, cat]) => {
        const cur = cat && cat.current;
        if (cur && fresh(cur.ts)) { relaying = true; if (!name) name = id; }
      });
      let status;
      if (dev.state === "recording") status = "recording";
      else if (dev.state === "inRange") status = "inRange";
      else if (dev.state === "approaching") status = "approaching";
      else if (relaying) status = "near";     // heard (telemetry relaying) but proximity idle, e.g. a resting collar
      else status = "away";
      const LABEL = { recording: "● recording", inRange: "at the station", approaching: "settling…",
                      near: "nearby", away: "not at the station" };
      const CLS   = { recording: "p-rec blink", inRange: "p-on", approaching: "p-near",
                      near: "p-on", away: "p-idle" };
      return { status, label: LABEL[status], cls: CLS[status], present: status !== "away", name };
    }

    // ---- live station status ----
    function renderStations(devices) {
      const wrap = document.getElementById("stations");
      const stations = Object.entries(devices || {}).filter(([, d]) => d && d.type === "station");
      if (!stations.length) { wrap.innerHTML = '<div class="empty">No stations registered yet.</div>'; return; }
      wrap.innerHTML = "";
      stations.forEach(([token, d]) => {
        const dev = d.dev || {};                  // { rssi, nearCollar, recording, state, collarBattery } (station writes this)
        const card = el("div", "dev-card");

        const head = el("div", "row between");
        const left = el("div");
        left.appendChild(el("div", "nm", d.name || "(unnamed station)"));
        left.appendChild(el("div", "devid", "ID " + token.slice(0, 10) + "…"));
        const online = fresh(d.lastSeen);
        const onWrap = el("div", "row");
        const dot = el("span", "dot " + (online ? "dot-on" : "dot-off"));
        onWrap.append(dot, el("span", "muted", online ? "online" : "offline"));
        head.append(left, onWrap);
        card.appendChild(head);

        // connection / proximity state , single source of truth, identical to the record gate
        const pres = collarPresence(d);
        const badge = el("span", "pill " + pres.cls, pres.label);
        const bWrap = el("div", "row"); bWrap.style.marginTop = ".6rem"; bWrap.appendChild(badge);
        if (pres.name) bWrap.appendChild(el("span", "muted", pres.name));
        card.appendChild(bWrap);

        const grid = el("div", "grid");
        const stat = (k, v) => { const s = el("div", "stat"); s.appendChild(el("div", "k", k)); s.appendChild(el("div", "v", v)); return s; };
        grid.appendChild(stat("Signal", typeof dev.rssi === "number" ? dev.rssi + " dBm" : "—"));
        grid.appendChild(stat("Threshold", (d.config && typeof d.config.rssiThreshold === "number") ? d.config.rssiThreshold + " dBm" : "—"));
        grid.appendChild(stat("Station power", d.power === "battery" ? ((typeof d.battery === "number" ? d.battery + "%" : "battery")) : "🔌 USB"));
        const cb = collarBattery(d);
        grid.appendChild(stat("Collar battery", cb != null ? cb + "%" : "—"));
        grid.appendChild(stat("Registered collars", typeof d.collars === "number" ? d.collars : "—"));
        grid.appendChild(stat("Last seen", typeof d.lastSeen === "number" ? Math.round((Date.now() - d.lastSeen) / 1000) + "s ago" : "—"));
        card.appendChild(grid);

        wrap.appendChild(card);
      });
    }

    // ---- recorded clips (index lives under each station: devices/{token}/clips) ----
    // One shared AudioContext for decoding + previewing every clip.
    let g_actx = null;
    function actx() { g_actx = g_actx || new (window.AudioContext || window.webkitAudioContext)(); return g_actx; }

    // Draw a min/max waveform of channel 0 across the canvas width.
    function drawWave(canvas, buf) {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      const ctx = canvas.getContext("2d");
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);
      const data = buf.getChannelData(0);
      const step = Math.max(1, Math.floor(data.length / w));
      const mid = h / 2;
      ctx.fillStyle = "#b9b3f0";
      for (let x = 0; x < w; x++) {
        let min = 1, max = -1;
        const s = x * step;
        for (let i = 0; i < step; i++) { const v = data[s + i] || 0; if (v < min) min = v; if (v > max) max = v; }
        const y1 = mid - max * mid * 0.92, y2 = mid - min * mid * 0.92;
        ctx.fillRect(x, y1, 1, Math.max(1, y2 - y1));
      }
    }

    // Local date+time the clip was recorded. c.ts is epoch ms (the clip key is the same value).
    // Returns a compact label for the row and a full one for the tooltip, or null if unknown.
    function clipWhen(c) {
      const ms = (typeof c.ts === "number") ? c.ts : Number(c.id);
      if (!ms || !isFinite(ms)) return null;
      const d = new Date(ms);
      return {
        short: d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }),
        full: d.toLocaleString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }),
      };
    }

    // Human-readable clip length: trimmed window if one's been saved, else the recorded duration.
    function lenText(c) {
      if (typeof c.trimStartMs === "number" && typeof c.trimEndMs === "number")
        return ((c.trimEndMs - c.trimStartMs) / 1000).toFixed(1) + "s ✂";
      return (c.durationSec != null) ? c.durationSec + "s" : "?";
    }

    // A clip row is COLLAPSED by default: just label, length and the IMU/audio-only badge , cheap, no
    // fetch. The heavy part (download + decode + waveform + trim markers + play) is built lazily on
    // expand and torn down on collapse, so a long list of clips stays light (only what you open loads).
    function buildClipRow(c) {
      const row = el("div", "clip");
      row.dataset.clipid = c.id;

      // ---- collapsed header (no audio fetched) ----
      const head = el("div", "chead");
      const lhs = el("div", "lhs");
      const chev = el("span", "chev", "▸");
      lhs.appendChild(chev);
      const sel = document.createElement("select");   // label, editable without loading audio
      sel.className = "sm";
      [["", "label…"], ...g_actions.map(a => [a, a])].forEach(([v, t]) => {
        const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o);
      });
      sel.value = c.label || "";
      sel.onclick = e => e.stopPropagation();   // don't toggle the row when using the dropdown
      sel.onchange = () => {
        if (g_demo) { sel.value = c.label || ""; return; }   // read-only demo: revert the dropdown, no write
        const ref = firebase.database().ref("users/" + g_uid + "/devices/" + c.token + "/clips/" + c.id + "/label");
        if (sel.value) { ref.set(sel.value); c.label = sel.value; } else { ref.remove(); c.label = null; }
      };
      lhs.appendChild(sel);
      const hasImu = !!(c.imuUrl || c.imuPath);
      const imu = el("span", "imu-badge" + (hasImu ? "" : " no"), hasImu ? "Motion ✓" : "audio only");
      if (hasImu) imu.title = (c.imuFrames || "?") + " frames @ " + (c.imuRateHz || "?") + " Hz, " + (c.imuAxes || 6) + " axes";
      lhs.appendChild(imu);
      head.appendChild(lhs);

      const rhs = el("div", "lhs");
      const when = clipWhen(c);
      if (when) { const tEl = el("span", "clip-time", when.short); tEl.title = "Recorded " + when.full; rhs.appendChild(tEl); }
      const lenEl = el("span", "devid", lenText(c));
      rhs.appendChild(lenEl);
      const del = el("button", "sm", "✕"); del.title = "Delete clip"; del.type = "button";
      rhs.appendChild(del);
      head.appendChild(rhs);
      row.appendChild(head);

      // ---- detail (built only while expanded) ----
      const detail = el("div", "cdetail hidden");
      row.appendChild(detail);

      let expanded = false, teardown = null;
      head.onclick = e => {
        if (e.target === del || (e.target.closest && e.target.closest("select"))) return;
        expanded = !expanded;
        chev.textContent = expanded ? "▾" : "▸";
        detail.classList.toggle("hidden", !expanded);
        if (expanded) {
          teardown = buildClipDetail(c, detail, t => lenEl.textContent = t);
        } else {
          if (teardown) { teardown(); teardown = null; }
          detail.innerHTML = "";   // free the canvas + decoded audio buffer
        }
      };

      del.onclick = async e => {
        e.preventDefault();
        e.stopPropagation();
        if (g_demo) return;   // read-only demo: no delete
        del.disabled = true;
        const path = "users/" + g_uid + "/devices/" + c.token + "/clips/" + c.id;
        try {
          await firebase.database().ref(path).remove();
          deleteClipFiles(c);   // also drop the Storage objects (audio + IMU), fire-and-forget
          // Optimistically pull the row now; the value listener will confirm on its next fire.
          if (clipEls[c.id]) { clipEls[c.id].row.remove(); delete clipEls[c.id]; }
        } catch (e2) {
          del.disabled = false;
          const m = (e2 && e2.message) ? e2.message : String(e2);
          del.title = "Delete failed: " + m;
          console.error("clip delete failed:", path, e2);
          alert("Couldn't delete clip:\n" + m);
        }
      };
      return row;
    }

    // The expensive part of a clip: fetch + decode the audio, draw the waveform, wire the trim markers
    // and play. Returns a teardown fn (stops playback) so the caller can release it on collapse.
    // `setLen` refreshes the collapsed header's length text after a trim is saved.
    function buildClipDetail(c, container, setLen) {
      const hasImu = !!(c.imuPath || c.imuUrl);
      const imuAxes = c.imuAxes || 6;
      const IMU_COLORS = ["#d1495b", "#2a9d8f", "#5b6cc2"];   // X, Y, Z

      // Audio waveform plus, when present, the time-aligned IMU motion as line graphs. All lanes
      // stack in one wrap so the trim window and playhead span audio + motion together.
      const wrap = el("div", "wave-wrap");
      const stack = el("div", "wave-stack");
      const lane = (cv, label) => {
        const d = el("div", "wave-lane"); d.appendChild(cv);
        if (label) d.appendChild(el("div", "wave-lane-label", label));
        return d;
      };
      const canvas = el("canvas", "wave-audio");
      stack.appendChild(lane(canvas, "audio"));
      let accelCv = null, gyroCv = null;
      if (hasImu) {
        accelCv = el("canvas", "wave-imu");
        stack.appendChild(lane(accelCv, "movement x·y·z"));
        if (imuAxes >= 6) { gyroCv = el("canvas", "wave-imu"); stack.appendChild(lane(gyroCv, "rotation x·y·z")); }
      }
      const dimL = el("div", "wave-dim"), dimR = el("div", "wave-dim");
      const mStart = el("div", "wave-marker start"), mEnd = el("div", "wave-marker end");
      const playhead = el("div", "wave-play");
      wrap.append(stack, dimL, dimR, mStart, mEnd, playhead);
      container.appendChild(wrap);

      const bar = el("div", "cbar");
      const playBtn = el("button", "sm primary", "▶ Play");
      const tnum = el("div", "tnum", "loading…");
      const saveBtn = el("button", "sm", "Save trim");
      const fullBtn = el("button", "sm", "Full");
      bar.append(playBtn, tnum, saveBtn, fullBtn);
      if (hasImu) {
        const lg = el("div", "imu-legend");
        // Built from IMU_COLORS so the legend swatches can't drift from the waveform line colours.
        lg.innerHTML = ["X", "Y", "Z"]
          .map((ax, i) => `<span><i style="background:${IMU_COLORS[i]}"></i>${ax}</span>`)
          .join("");
        bar.appendChild(lg);
      }
      container.appendChild(bar);

      let buf = null, durMs = 0, src = null, raf = 0;
      let cancelled = false, imuData = null;
      let aMs = (typeof c.trimStartMs === "number") ? c.trimStartMs : 0;
      let bMs = (typeof c.trimEndMs === "number") ? c.trimEndMs : null;
      const fmt = ms => (ms / 1000).toFixed(2) + "s";
      function layout() {
        if (!durMs) return;
        const w = wrap.clientWidth;
        const ax = (aMs / durMs) * w, bx = (bMs / durMs) * w;
        mStart.style.left = ax + "px"; mEnd.style.left = bx + "px";
        dimL.style.left = "0"; dimL.style.width = ax + "px";
        dimR.style.left = bx + "px"; dimR.style.width = Math.max(0, w - bx) + "px";
        tnum.textContent = fmt(aMs) + " – " + fmt(bMs) + "  (" + ((bMs - aMs) / 1000).toFixed(2) + "s)";
      }

      // In the read-only demo the audio lives in private Storage (a public visitor would 403), so don't
      // even attempt the fetch , just say so. The waveform/trim/play stay inert.
      if (g_demo) { tnum.textContent = "audio hidden in demo"; return () => {}; }

      // New clips store an owner-scoped Storage path, resolved via the authed SDK (getDownloadURL
      // returns a tokened URL the rules allow). Older/flat clips stored a direct ?alt=media URL.
      const audioUrl = c.path ? firebase.storage().ref(c.path).getDownloadURL() : Promise.resolve(c.url || null);
      audioUrl.then(u => {
        if (!u) { tnum.textContent = "no audio"; return; }
        return fetch(u).then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
          .then(ab => actx().decodeAudioData(ab))
          .then(b => {
            buf = b; durMs = b.duration * 1000;
            if (bMs == null) bMs = durMs;
            aMs = Math.max(0, Math.min(aMs, durMs)); bMs = Math.max(aMs, Math.min(bMs, durMs));
            drawWave(canvas, b); layout(); drawImuLanes();
          });
      }).catch(e => {
        // Surface the REAL reason so a load failure is self-diagnosing (the full error + path also go
        // to the browser console). Usual culprits: "TypeError: Failed to fetch" = the Storage bucket
        // has no CORS policy for this origin; "storage/unauthorized" or "HTTP 403" = the rules deny
        // this user (uid mismatch); "storage/object-not-found" / "HTTP 404" = the audio isn't in
        // Storage; an EncodingError = the bytes aren't a decodable WAV.
        console.error("clip audio load failed:", c.path || c.url, e);
        tnum.textContent = "audio: " + ((e && (e.code || e.message)) || e);
      });

      // ---- IMU motion: raw little-endian int16, imuAxes interleaved per frame at imuRateHz ----
      // Drawn as line graphs on the same time axis as the audio (x = frame_time / clip_duration),
      // so the motion lines up with the sound and shares the trim window above.
      function drawImuLane(cv, axisIdx) {
        if (!cv || !imuData) return;
        const axes = imuAxes, rate = c.imuRateHz || 100;
        const n = Math.floor(imuData.length / axes);
        if (!n) return;
        const dpr = window.devicePixelRatio || 1;
        const w = cv.clientWidth || 1, h = cv.clientHeight || 1;
        cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
        const ctx = cv.getContext("2d"); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
        // normalise each lane by its own peak so accel and gyro both fill the height
        let maxAbs = 1;
        for (let i = 0; i < n; i++) for (const a of axisIdx) { const v = Math.abs(imuData[i * axes + a]); if (v > maxAbs) maxAbs = v; }
        const mid = h / 2, amp = (h / 2) * 0.86;
        ctx.strokeStyle = "#dcdce6"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(w, mid); ctx.stroke();   // zero line
        const total = durMs || (n / rate * 1000);                                // align to audio time
        const xScale = w / total;
        const step = Math.max(1, Math.floor(n / (w * 2)));
        axisIdx.forEach((a, k) => {
          ctx.strokeStyle = IMU_COLORS[k]; ctx.lineWidth = 1.2; ctx.lineJoin = "round";
          ctx.beginPath();
          let first = true;
          for (let i = 0; i < n; i += step) {
            const x = (i / rate * 1000) * xScale;
            const y = mid - (imuData[i * axes + a] / maxAbs) * amp;
            if (first) { ctx.moveTo(x, y); first = false; } else ctx.lineTo(x, y);
          }
          ctx.stroke();
        });
      }
      function drawImuLanes() {
        if (cancelled || !imuData || !durMs) return;   // need the audio duration to align the time axis
        drawImuLane(accelCv, [0, 1, 2]);
        if (gyroCv && imuAxes >= 6) drawImuLane(gyroCv, [3, 4, 5]);
      }
      if (hasImu) {
        const imuUrl = c.imuPath ? firebase.storage().ref(c.imuPath).getDownloadURL() : Promise.resolve(c.imuUrl || null);
        imuUrl.then(u => (u ? fetch(u) : null))
          .then(r => { if (!r) return null; if (!r.ok) throw new Error("HTTP " + r.status); return r.arrayBuffer(); })
          .then(ab => {
            if (!ab || cancelled) return;
            imuData = new Int16Array(ab, 0, Math.floor(ab.byteLength / 2));   // little-endian int16
            drawImuLanes();
          })
          .catch(e => { console.error("clip IMU load failed:", c.imuPath || c.imuUrl, e); });
      }

      function dragMarker(which) {
        return down => {
          down.preventDefault();
          const move = e => {
            if (!durMs) return;
            const rect = wrap.getBoundingClientRect();
            const cx = (e.touches ? e.touches[0].clientX : e.clientX) - rect.left;
            const ms = (Math.min(rect.width, Math.max(0, cx)) / rect.width) * durMs;
            const gap = 50;   // keep at least 50 ms selected
            if (which === "a") aMs = Math.max(0, Math.min(ms, bMs - gap));
            else bMs = Math.min(durMs, Math.max(ms, aMs + gap));
            layout();
          };
          const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
          window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
        };
      }
      mStart.addEventListener("pointerdown", dragMarker("a"));
      mEnd.addEventListener("pointerdown", dragMarker("b"));

      playBtn.onclick = async () => {
        if (!buf) return;
        if (src) { try { src.stop(); } catch (e) {} src = null; cancelAnimationFrame(raf); playhead.style.display = "none"; return; }
        await actx().resume();
        src = actx().createBufferSource(); src.buffer = buf; src.connect(actx().destination);
        const t0 = actx().currentTime, w = wrap.clientWidth;
        src.start(0, aMs / 1000, (bMs - aMs) / 1000);
        playhead.style.display = "block";
        const tick = () => {
          const ms = aMs + (actx().currentTime - t0) * 1000;
          playhead.style.left = ((ms / durMs) * w) + "px";
          if (src && ms < bMs) raf = requestAnimationFrame(tick); else playhead.style.display = "none";
        };
        raf = requestAnimationFrame(tick);
        src.onended = () => { cancelAnimationFrame(raf); playhead.style.display = "none"; src = null; };
      };

      saveBtn.onclick = async () => {
        if (g_demo) return;   // read-only demo: no trim save
        if (!durMs) return;
        saveBtn.disabled = true; const old = saveBtn.textContent; saveBtn.textContent = "Saving…";
        try {
          await firebase.database().ref("users/" + g_uid + "/devices/" + c.token + "/clips/" + c.id)
            .update({ trimStartMs: Math.round(aMs), trimEndMs: Math.round(bMs) });
          c.trimStartMs = Math.round(aMs); c.trimEndMs = Math.round(bMs);   // keep the row in sync
          setLen(lenText(c));
          saveBtn.textContent = "Saved ✓";
        } catch (e) { saveBtn.textContent = "Failed"; }
        setTimeout(() => { saveBtn.textContent = old; saveBtn.disabled = false; }, 1200);
      };
      fullBtn.onclick = () => { aMs = 0; bMs = durMs; layout(); };

      return () => { cancelled = true; if (src) { try { src.stop(); } catch (e) {} } cancelAnimationFrame(raf); };
    }

    // Delete a clip's Storage objects (audio + IMU sidecar) with the authed SDK. The old approach
    // used a raw fetch(DELETE) which Storage rejected, so files piled up in the bucket. refFromURL
    // parses the bucket+path from the download URL and deletes via the proper endpoint. Errors are
    // swallowed (a file may already be gone). Returns a promise that resolves when both are tried.
    function deleteClipFiles(c) {
      const st = firebase.storage();
      const ps = [];
      // New clips: owner-scoped Storage paths (delete by path). Legacy/flat clips: download URLs
      // (refFromURL parses the bucket+path). Errors are swallowed (a file may already be gone).
      [c.path, c.imuPath].forEach(p => {
        if (!p) return;
        try { ps.push(st.ref(p).delete().catch(() => {})); } catch (e) {}
      });
      [c.url, c.imuUrl].forEach(u => {
        if (!u) return;
        try { ps.push(st.refFromURL(u).delete().catch(() => {})); } catch (e) {}
      });
      return Promise.all(ps);
    }

    // Bulk delete EVERY clip (rows + Storage files). Built for cleaning up the hundreds of clips a
    // runaway capture can leave behind. Files go in small concurrent batches; DB rows are wiped per
    // device in a single node removal so we don't issue hundreds of separate writes.
    async function deleteAllClips() {
      if (g_demo) return;   // read-only demo: no bulk delete
      const all = [];
      Object.entries(lastDevices || {}).forEach(([token, d]) => {
        if (d && d.type === "station" && d.clips)
          Object.entries(d.clips).forEach(([id, c]) => all.push({ id, token, ...c }));
      });
      const btn = document.getElementById("delAll");
      if (!all.length) { alert("No clips to delete."); return; }
      if (!confirm("Delete ALL " + all.length + " clips and their audio/motion files?\nThis cannot be undone.")) return;
      const old = btn.textContent; btn.disabled = true;
      let done = 0;
      for (let i = 0; i < all.length; i += 12) {
        const batch = all.slice(i, i + 12);
        await Promise.all(batch.map(c => deleteClipFiles(c)));
        done += batch.length;
        btn.textContent = "Deleting " + done + "/" + all.length + "…";
      }
      // Wipe each device's whole clips node in one write.
      const tokens = [...new Set(all.map(c => c.token))];
      let dbErr = null;
      try {
        await Promise.all(tokens.map(t =>
          firebase.database().ref("users/" + g_uid + "/devices/" + t + "/clips").remove()));
      } catch (e) { dbErr = e; }
      Object.keys(clipEls).forEach(id => { clipEls[id].row.remove(); delete clipEls[id]; });
      btn.textContent = old; btn.disabled = false;
      if (dbErr) { alert("Files deleted, but clearing rows failed: " + (dbErr.message || dbErr)); }
      else alert("Deleted " + all.length + " clips and their files.");
    }

    // ---- clip grouping: Day > Session > Clip, each a collapsible disclosure ----
    // A "session" is a run of clips in the same or consecutive minute (a continuous recording);
    // a gap of a whole empty minute starts a new session. Open/closed state lives in openGroups
    // so it survives the rebuilds that happen as new clips arrive.
    let openGroups = new Set();
    let groupsSeeded = false;

    function clipTs(c) { return (typeof c.ts === "number") ? c.ts : (Number(c.id) || 0); }
    function minuteBucket(ts) { return Math.floor(ts / 60000); }

    function dayInfo(ts) {
      const d = new Date(ts);
      const key = d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate();
      const same = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
      const now = new Date(), yest = new Date(Date.now() - 86400000);
      let label;
      if (same(d, now)) label = "Today";
      else if (same(d, yest)) label = "Yesterday";
      else label = d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
      return { key, label };
    }
    function sessionTimeRange(sess) {
      const t = ms => new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
      const a = t(clipTs(sess[0])), b = t(clipTs(sess[sess.length - 1]));
      return a === b ? a : (a + "–" + b);
    }
    function sessionLabel(sess) {
      const labels = new Set(sess.map(c => c.label).filter(Boolean));
      if (!labels.size) return "unlabelled";
      return labels.size === 1 ? [...labels][0] : "mixed";
    }
    function toggleGroup(key, head, body) {
      const open = !body.classList.toggle("hidden");   // toggle returns true when 'hidden' is now set
      if (open) openGroups.add(key); else openGroups.delete(key);
      const chev = head.querySelector(".chev"); if (chev) chev.textContent = open ? "▾" : "▸";
    }
    function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }

    // Recommended minimum labelled clips per category before training. Easy to tune.
    const MIN_PER_CLASS = 30;

    // Motion-variety analysis state (filled on demand by analyzeVariety).
    let g_featCache = {};        // clipId -> {vec, label}  (downloaded motion features, cached)
    let g_variety = null;        // { byLabel: {label: {n, sim, variety}}, total } after a run
    let g_varietyBusy = false, g_varietyProgress = "", g_analyseBtn = null;

    // Count distinct recording sessions in a set of clips, using the same minute-bucket chaining
    // as the clip grouping (same or consecutive minute = one session).
    function countSessions(clips) {
      const sorted = clips.slice().sort((a, b) => clipTs(a) - clipTs(b));
      let n = 0, prev = null;
      sorted.forEach(c => { const m = minuteBucket(clipTs(c)); if (prev === null || m - prev > 1) n++; prev = m; });
      return n;
    }
    function varietyClass(v) { return v < 34 ? "v-low" : (v < 60 ? "v-mid" : "v-high"); }
    function varietyLabel(v) { return v < 34 ? "Too similar" : (v < 60 ? "Some variety" : "Good variety"); }
    function varietyHint(v, lab) {
      if (v < 34) return "Your '" + lab + "' clips are nearly all the same, so the model may not generalise. Record this action in more situations: different times, places and postures.";
      if (v < 60) return "Your '" + lab + "' clips have some variety. A few more varied sessions would still help.";
      return "Your '" + lab + "' clips are well varied across your recordings.";
    }

    // A compact motion fingerprint for a clip: per-axis mean (posture/orientation) and std (intensity).
    function imuFeatures(frames, axes, rate, trimStart, trimEnd) {
      const n0 = Math.floor(frames.length / axes);
      let lo = 0, hi = n0;
      if (typeof trimStart === "number" && rate) lo = Math.max(0, Math.floor(trimStart * rate / 1000));
      if (typeof trimEnd === "number" && rate) hi = Math.min(n0, Math.ceil(trimEnd * rate / 1000));
      if (hi - lo < 2) { lo = 0; hi = n0; }
      const n = Math.max(1, hi - lo), f = [];
      for (let a = 0; a < axes; a++) {
        let s = 0, s2 = 0;
        for (let i = lo; i < hi; i++) { const v = frames[i * axes + a]; s += v; s2 += v * v; }
        const m = s / n, vr = Math.max(0, s2 / n - m * m);
        f.push(m, Math.sqrt(vr));
      }
      return f;
    }
    async function runPool(items, limit, fn) {
      let i = 0;
      await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
        while (i < items.length) { const idx = i++; await fn(items[idx], idx); }
      }));
    }
    function setAnalyseProgress(txt) { g_varietyProgress = txt; if (g_analyseBtn) g_analyseBtn.textContent = txt; }

    // Variety per category = 1 - average within-class similarity. Features are standardised, then
    // compared with a Gaussian (RBF) kernel whose scale is the median pairwise distance, so a class
    // of near-identical clips scores ~0 and a well-spread class scores high.
    function computeVariety(items) {
      const D = items[0].vec.length, N = items.length;
      const mean = new Array(D).fill(0), sd = new Array(D).fill(0);
      items.forEach(it => { for (let k = 0; k < D; k++) mean[k] += it.vec[k]; });
      for (let k = 0; k < D; k++) mean[k] /= N;
      items.forEach(it => { for (let k = 0; k < D; k++) { const d = it.vec[k] - mean[k]; sd[k] += d * d; } });
      for (let k = 0; k < D; k++) { sd[k] = Math.sqrt(sd[k] / N) || 1; }
      const Z = items.map(it => it.vec.map((v, k) => (v - mean[k]) / sd[k]));
      const d2 = (a, b) => { let s = 0; for (let k = 0; k < a.length; k++) { const d = a[k] - b[k]; s += d * d; } return s; };
      const sample = [], maxPairs = 6000;
      if (N * (N - 1) / 2 <= maxPairs) { for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) sample.push(d2(Z[i], Z[j])); }
      else { for (let p = 0; p < maxPairs; p++) { const i = (Math.random() * N) | 0, j = (Math.random() * N) | 0; if (i !== j) sample.push(d2(Z[i], Z[j])); } }
      sample.sort((a, b) => a - b);
      const sigma2 = (sample[Math.floor(sample.length / 2)] || 1) || 1;
      const groups = {};
      items.forEach((it, idx) => { (groups[it.label] = groups[it.label] || []).push(idx); });
      const byLabel = {};
      Object.keys(groups).forEach(lab => {
        const idx = groups[lab];
        let sum = 0, cnt = 0;
        for (let i = 0; i < idx.length; i++) for (let j = i + 1; j < idx.length; j++) { sum += Math.exp(-d2(Z[idx[i]], Z[idx[j]]) / (2 * sigma2)); cnt++; }
        const sim = cnt ? sum / cnt : null;
        byLabel[lab] = { n: idx.length, sim, variety: sim == null ? null : Math.round((1 - sim) * 100) };
      });
      return { byLabel, total: N };
    }

    // Download each labelled clip's motion data, fingerprint it, and score per-category variety.
    async function analyzeVariety() {
      if (g_demo || g_varietyBusy) return;
      const clips = [];
      Object.entries(lastDevices || {}).forEach(([token, d]) => {
        if (d && d.type === "station" && d.clips) Object.entries(d.clips).forEach(([id, c]) => {
          if (c.label && (c.imuPath || c.imuUrl)) clips.push({ id, token, ...c });
        });
      });
      if (clips.length < 2) { alert("Need at least 2 labelled clips with motion data to compare."); return; }
      g_varietyBusy = true; setAnalyseProgress("Analysing… 0/" + clips.length);
      const todo = clips.filter(c => !g_featCache[c.id]);
      let done = clips.length - todo.length;
      await runPool(todo, 8, async c => {
        try {
          const u = c.imuPath ? await firebase.storage().ref(c.imuPath).getDownloadURL() : c.imuUrl;
          if (u) {
            const ab = await (await fetch(u)).arrayBuffer();
            const frames = new Int16Array(ab, 0, Math.floor(ab.byteLength / 2));
            g_featCache[c.id] = { vec: imuFeatures(frames, c.imuAxes || 6, c.imuRateHz || 104, c.trimStartMs, c.trimEndMs), label: c.label };
          }
        } catch (e) { console.error("variety: motion load failed", c.id, e); }
        done++; setAnalyseProgress("Analysing… " + done + "/" + clips.length);
      });
      // keep features current with each clip's latest label
      clips.forEach(c => { if (g_featCache[c.id]) g_featCache[c.id].label = c.label; });
      const items = clips.map(c => g_featCache[c.id]).filter(Boolean);
      g_variety = items.length >= 2 ? computeVariety(items) : null;
      g_varietyBusy = false; g_varietyProgress = "";
      lastClipsSig = ""; renderClips(lastDevices);   // one rebuild to show the scores
    }

    // Dataset stats: per category, clip and session counts, a minimum-clip progress mark, and (after
    // an analysis run) a motion-variety score. Rebuilt whenever clips or labels change.
    function buildClipStats(all) {
      const byLabel = {};
      let unl = 0;
      all.forEach(c => { if (c.label) (byLabel[c.label] = byLabel[c.label] || []).push(c); else unl++; });
      const box = el("div", "clip-stats");

      const head = el("div", "cs-summary");
      head.appendChild(el("span", null, plural(all.length, "clip") + " · " + unl + " unlabelled"));
      const btn = el("button", "sm cs-analyse");
      btn.type = "button";
      btn.textContent = g_varietyBusy ? (g_varietyProgress || "Analysing…") : (g_variety ? "Re-analyse motion variety" : "Analyse motion variety");
      btn.disabled = !!(g_demo || g_varietyBusy);
      btn.onclick = analyzeVariety;
      head.appendChild(btn);
      g_analyseBtn = btn;
      box.appendChild(head);

      if (g_variety) box.appendChild(el("div", "cs-note",
        "Variety = how different an action's clips are from each other. Aim for ‘Good variety’ by recording each action in varied situations."));

      const chips = el("div", "cs-chips");
      const cats = [...g_actions];
      Object.keys(byLabel).forEach(l => { if (!cats.includes(l)) cats.push(l); });   // include stray labels too
      cats.forEach(a => {
        const clips = byLabel[a] || [], n = clips.length, sessions = countSessions(clips);
        const chip = el("span", "cs-chip " + (n >= MIN_PER_CLASS ? "met" : (n > 0 ? "low" : "none")));
        chip.appendChild(el("span", "cs-lbl", a));
        chip.appendChild(el("span", "cs-num", n + " clip" + (n === 1 ? "" : "s") + " · " + plural(sessions, "session")));
        const v = g_variety && g_variety.byLabel[a];
        if (v && v.variety != null) {
          const vb = el("span", "cs-var " + varietyClass(v.variety), varietyLabel(v.variety));
          vb.title = varietyHint(v.variety, a);
          chip.appendChild(vb);
        }
        const bar = el("span", "cs-bar"), fill = el("i");
        fill.style.width = Math.min(100, Math.round(n / MIN_PER_CLASS * 100)) + "%";
        bar.appendChild(fill); chip.appendChild(bar);
        chips.appendChild(chip);
      });
      if (unl) {
        const chip = el("span", "cs-chip unl");
        chip.appendChild(el("span", "cs-lbl", "unlabelled"));
        chip.appendChild(el("span", "cs-num", unl + " clip" + (unl === 1 ? "" : "s")));
        chips.appendChild(chip);
      }
      box.appendChild(chips);
      return box;
    }

    function renderClips(devices) {
      maybeLabelNewClips(devices);   // auto-label clips arriving during a live-label session
      const wrap = document.getElementById("clips");
      if (!wrap) return;
      const all = [];
      Object.entries(devices || {}).forEach(([token, d]) => {
        if (d && d.type === "station" && d.clips)
          Object.entries(d.clips).forEach(([id, c]) => all.push({ id, token, ...c }));
      });
      if (!all.length) { wrap.innerHTML = '<div class="empty">No clips yet.</div>'; clipEls = {}; lastClipsSig = ""; return; }
      all.sort((a, b) => clipTs(a) - clipTs(b));   // ascending, so sessions chain in recording order

      // Skip the rebuild when neither the clip set nor any label changed (the 5 s refresh tick, etc.).
      const sig = all.map(c => c.id + ":" + (c.label || "")).join("|");
      if (sig === lastClipsSig) return;
      lastClipsSig = sig;

      // Build Day -> Sessions, chaining clips while consecutive minute buckets differ by <= 1.
      const days = [], dayMap = {};
      all.forEach(c => {
        const di = dayInfo(clipTs(c));
        let day = dayMap[di.key];
        if (!day) { day = dayMap[di.key] = { key: di.key, label: di.label, sessions: [] }; days.push(day); }
        const last = day.sessions[day.sessions.length - 1];
        const prev = last && last[last.length - 1];
        if (prev && minuteBucket(clipTs(c)) - minuteBucket(clipTs(prev)) <= 1) last.push(c);
        else day.sessions.push([c]);
      });

      // First paint: open the newest day and its newest session so the latest clips are visible.
      if (!groupsSeeded) {
        groupsSeeded = true;
        const nd = days[days.length - 1];
        openGroups.add("day:" + nd.key);
        const ns = nd.sessions[nd.sessions.length - 1];
        if (ns) openGroups.add("sess:" + ns[0].id);
      }

      clipEls = {};
      wrap.innerHTML = "";
      wrap.appendChild(buildClipStats(all));                        // dataset stats on top
      days.slice().reverse().forEach(day => {                       // newest day first
        const totalClips = day.sessions.reduce((n, s) => n + s.length, 0);
        const dayKey = "day:" + day.key, dayOpen = openGroups.has(dayKey);
        const dayWrap = el("div", "day-group");
        const dayHead = el("div", "group-head day-head");
        dayHead.appendChild(el("span", "chev", dayOpen ? "▾" : "▸"));
        dayHead.appendChild(el("span", "g-title", day.label));
        dayHead.appendChild(el("span", "g-meta", plural(totalClips, "clip") + " · " + plural(day.sessions.length, "session")));
        const dayBody = el("div", "group-body" + (dayOpen ? "" : " hidden"));
        dayHead.onclick = () => toggleGroup(dayKey, dayHead, dayBody);
        dayWrap.append(dayHead, dayBody);

        day.sessions.slice().reverse().forEach(sess => {            // newest session first
          const sKey = "sess:" + sess[0].id, sOpen = openGroups.has(sKey);
          const sWrap = el("div", "session-group");
          const sHead = el("div", "group-head sess-head");
          sHead.appendChild(el("span", "chev", sOpen ? "▾" : "▸"));
          sHead.appendChild(el("span", "g-title", sessionTimeRange(sess)));
          sHead.appendChild(el("span", "g-meta", sess.length + " · " + sessionLabel(sess)));
          const sBody = el("div", "group-body" + (sOpen ? "" : " hidden"));
          sHead.onclick = () => toggleGroup(sKey, sHead, sBody);
          sess.slice().reverse().forEach(c => {                     // newest clip first within a session
            const row = buildClipRow(c);
            clipEls[c.id] = { row };
            sBody.appendChild(row);
          });
          sWrap.append(sHead, sBody);
          dayBody.appendChild(sWrap);
        });
        wrap.appendChild(dayWrap);
      });
    }

    function renderAll() {
      try { renderStations(lastDevices); } catch (e) { console.error("renderStations failed:", e); }
      try { renderClips(lastDevices); } catch (e) { console.error("renderClips failed:", e); }
      try { renderActivityStatus(); } catch (e) { console.error("renderActivityStatus failed:", e); }   // refresh connection state
    }

    function attach(uid) {
      devicesRef = firebase.database().ref("users/" + uid + "/devices");
      devicesRef.on("value", s => { lastDevices = s.val() || {}; renderAll(); loadConfig(); });
      modelsRef = firebase.database().ref("users/" + uid + "/models");
      modelsRef.on("value", s => renderModels(s.val()));   // live cloud-training status
      actionsRef = firebase.database().ref("users/" + uid + "/actions");
      actionsRef.on("value", s => {
        const a = s.val();
        g_actions = (Array.isArray(a) && a.length) ? a : ["eat", "drink", "resting", "moving"];
        renderActions();
        renderActivityButtons();
        // refresh clip dropdowns so new actions appear as options (force a rebuild)
        lastClipsSig = "";
        renderClips(lastDevices);
      });
      timer = setInterval(renderAll, 5000);   // refresh freshness/"Xs ago"
    }

    // ---- cloud training (Firebase Function) ----
    const TRAIN_FN_URL = "https://europe-west1-meowtion-app.cloudfunctions.net/train";  // set once the Cloud Function is deployed
    function renderActions() {
      const el = document.getElementById("actionList");
      if (!el) return;
      el.innerHTML = "";
      g_actions.forEach(a => { const c = el.appendChild(document.createElement("span")); c.className = "devid"; c.textContent = a; });
    }
    async function addAction() {
      if (g_demo) return msg("action-msg", "Read-only demo , sign in with a dev account to make changes.", "err");
      const inp = document.getElementById("newAction");
      const v = (inp.value || "").trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
      if (!v) return;
      if (g_actions.includes(v)) return msg("action-msg", "Already in the list.", "err");
      try {
        await firebase.database().ref("users/" + g_uid + "/actions").set([...g_actions, v]);
        inp.value = ""; msg("action-msg", "Added '" + v + "'.", "ok");   // listener refreshes the list + dropdowns
      } catch (e) { msg("action-msg", e.message || "Failed.", "err"); }
    }
    function renderModels(m) {
      const el = document.getElementById("modelStatus");
      if (!m) { el.textContent = "No models trained yet."; return; }
      const p = [];
      if (m.status)  p.push("status: " + m.status);
      if (m.version) p.push("v" + m.version);
      ["imu", "audio"].forEach(k => {
        const r = m.results && m.results[k];
        if (r) p.push(`${k} ${(r.test_acc * 100).toFixed(0)}% (${r.bytes} B)`);
      });
      if (m.error) p.push("error: " + m.error);
      el.textContent = p.join("  ·  ");
    }
    async function retrainModels() {
      if (g_demo) return msg("train-msg", "Read-only demo , sign in with a dev account to make changes.", "err");
      const btn = document.getElementById("trainBtn");
      btn.disabled = true;
      msg("train-msg", "Training on the server , this can take a few minutes. Status updates below.", "ok");
      try {
        const tok = await firebase.auth().currentUser.getIdToken();
        const r = await fetch(TRAIN_FN_URL, { method: "POST", headers: { Authorization: "Bearer " + tok } });
        const txt = await r.text();
        msg("train-msg", r.ok ? ("Done. " + txt) : ("Failed: " + txt), r.ok ? "ok" : "err");
      } catch (e) {
        msg("train-msg", "Error: " + (e.message || e), "err");
      } finally {
        btn.disabled = false;
      }
    }

    // ---- capture on/off (written here, read by the station) ----
    let g_captureOn = false;
    let g_forceOn = false;
    let g_production = false;
    function renderCapBtn() {   // sync the toggle switches to their flags
      document.getElementById("capToggle").checked = g_captureOn;
      document.getElementById("capState").textContent = g_captureOn ? "On" : "Off";
      document.getElementById("modeToggle").checked = g_production;
      document.getElementById("modeState").textContent = g_production ? "Production" : "Training";
    }
    async function toggleMode() {
      if (g_demo) { renderCapBtn(); return msg("mode-msg", "Read-only demo , sign in with a dev account to make changes.", "err"); }
      const next = document.getElementById("modeToggle").checked;   // true = production
      const tokens = Object.entries(lastDevices).filter(([, d]) => d && d.type === "station").map(([t]) => t);
      if (!tokens.length) { renderCapBtn(); return msg("mode-msg", "No stations to control.", "err"); }
      const updates = {};
      tokens.forEach(t => { updates["users/" + g_uid + "/devices/" + t + "/config/mode"] = next ? "production" : "training"; });
      try {
        await firebase.database().ref().update(updates);
        g_production = next; renderCapBtn();
        msg("mode-msg", next ? "Production , recording/uploads stopped; relaying on-collar classification."
                             : "Training , recording enabled.", "ok");
      } catch (e) {
        renderCapBtn();   // revert the switch , the write didn't land
        msg("mode-msg", e.message || "Failed.", "err");
      }
    }
    // ---- live-label capture: press an action button, record a timed session at ANY distance, and
    // auto-label every clip that arrives during the window. Reuses the station's captureForce flag
    // (ignore-range) , no firmware change. Replaces the old manual force toggle. ----
    let g_session = null;
    let g_focusOpen = false, g_focusEl = null;

    // Is a collar actually connected to a station right now? Clips can't be buffered on the collar
    // (its RAM is tiny), so recording only works while a station is online AND hearing the collar.
    function recordReadiness() {
      const stations = Object.values(lastDevices || {}).filter(d => d && d.type === "station");
      if (!stations.length) return { ok: false, msg: "No station registered. Connect a station first." };
      const online = stations.filter(d => fresh(d.lastSeen));
      if (!online.length) return { ok: false, msg: "Station offline. Check it's powered and on Wi-Fi." };
      // Recordable when an online station is hearing the collar , the SAME collarPresence() the card
      // badge uses, so the record gate and the card can never disagree.
      const heard = online.some(d => collarPresence(d).present);
      if (!heard) return { ok: false, msg: "Collar not connected to the station. Bring the cat near the station, the collar must be heard while recording (clips can't be stored on the collar)." };
      return { ok: true, msg: "" };
    }

    // Debounce the NEGATIVE state for display so a brief blip (a resting collar between slow adverts,
    // a capture's reconnect, the post-save window) doesn't flash "not connected" / "offline". Going
    // ready shows instantly; going not-ready must hold for READY_DEBOUNCE_MS before the warning and the
    // disabled buttons appear. The actual start-recording gate (startActivity) still uses the raw
    // recordReadiness(), so we never start a session when genuinely not connected.
    let g_notReadySince = 0, g_readyTimer = 0;
    const READY_DEBOUNCE_MS = 5000;
    function readinessForDisplay() {
      const r = recordReadiness();
      if (r.ok) { g_notReadySince = 0; if (g_readyTimer) { clearTimeout(g_readyTimer); g_readyTimer = 0; } return r; }
      const now = Date.now();
      if (!g_notReadySince) g_notReadySince = now;
      const held = now - g_notReadySince;
      if (held < READY_DEBOUNCE_MS) {
        // still within the grace window: keep the last-good look, and schedule one re-render so the
        // warning appears if the outage persists (device updates alone might not fire during a gap).
        if (!g_readyTimer) g_readyTimer = setTimeout(() => { g_readyTimer = 0; renderActivityStatus(); }, READY_DEBOUNCE_MS - held + 50);
        return { ok: true, msg: "", pending: true };
      }
      return r;
    }

    // ---- focused "phone app" record view: one big-button screen, easy to tap while following the cat ----
    function createFocusOverlay() {
      if (g_focusEl) return g_focusEl;
      const ov = el("div", "rec-focus hidden");
      ov.innerHTML =
        '<div class="rec-focus-inner">' +
          '<div class="rec-focus-head"><div class="rec-focus-title">What is your cat doing?</div>' +
          '<button class="rec-focus-close" type="button" aria-label="Close">✕</button></div>' +
          '<div class="rec-focus-warn hidden"></div>' +
          '<div class="rec-focus-status"></div>' +
          '<div class="rec-focus-btns"></div>' +
          '<div class="rec-focus-foot"><span class="rec-focus-len">Length ' +
          '<select class="rec-focus-secs"></select></span>' +
          '<button class="rec-focus-stop" type="button">■ Stop</button></div>' +
        '</div>';
      ov.querySelector(".rec-focus-close").onclick = closeFocus;
      ov.querySelector(".rec-focus-stop").onclick = () => stopActivity("manual");
      const sel = ov.querySelector(".rec-focus-secs");
      [["5", "5s"], ["10", "10s"], ["15", "15s"], ["30", "30s"]].forEach(([v, t]) => {
        const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o);
      });
      const a0 = document.getElementById("actSecs");
      sel.value = (a0 && a0.value) || "30";
      sel.onchange = () => { const a = document.getElementById("actSecs"); if (a) a.value = sel.value; };
      document.body.appendChild(ov);
      g_focusEl = ov;
      return ov;
    }
    function openFocus() {
      if (g_demo) return;
      createFocusOverlay();
      g_focusOpen = true;
      g_focusEl.classList.remove("hidden");
      document.body.classList.add("rec-focus-on");
      renderActivityStatus();
    }
    function closeFocus() {
      g_focusOpen = false;
      if (g_focusEl) g_focusEl.classList.add("hidden");
      document.body.classList.remove("rec-focus-on");
    }
    function renderFocus(ready) {
      if (!g_focusOpen || !g_focusEl) return;
      ready = ready || readinessForDisplay();
      const s = g_session, recording = !!(s && s.active);
      const warn = g_focusEl.querySelector(".rec-focus-warn");
      if (!ready.ok && !recording) { warn.textContent = "⚠ " + ready.msg; warn.classList.remove("hidden"); }
      else warn.classList.add("hidden");
      const st = g_focusEl.querySelector(".rec-focus-status");
      if (recording) {
        const left = Math.max(0, Math.ceil((s.endAt - Date.now()) / 1000));
        st.textContent = "⏺ Recording ‘" + s.label + "’ — " + left + "s left" + (s.labelled ? " (" + s.labelled + " clip" + (s.labelled > 1 ? "s" : "") + ")" : "");
        st.className = "rec-focus-status on";
      } else if (s) { st.textContent = "Saving ‘" + s.label + "’…"; st.className = "rec-focus-status"; }
      else { st.textContent = ready.ok ? "Tap what your cat is doing now" : ""; st.className = "rec-focus-status"; }
      g_focusEl.querySelector(".rec-focus-stop").style.display = recording ? "" : "none";
      const btns = g_focusEl.querySelector(".rec-focus-btns");
      btns.innerHTML = "";
      if (!g_actions.length) { btns.appendChild(el("div", "rec-focus-empty", "Add actions first (in the Actions card).")); return; }
      g_actions.forEach(a => {
        const b = el("button", "rec-focus-btn" + (recording && a === s.label ? " active" : ""), a);
        b.type = "button"; b.disabled = recording || !ready.ok;
        b.onclick = () => startActivity(a);
        btns.appendChild(b);
      });
    }

    function renderActivityButtons() {
      const wrap = document.getElementById("activityBtns");
      if (!wrap) return;
      wrap.innerHTML = "";
      if (!g_actions.length) {
        wrap.innerHTML = '<span class="muted" style="font-size:.85rem;">Add actions above to get buttons here.</span>';
        return;
      }
      g_actions.forEach(a => {
        const b = el("button", "sm", a);
        b.type = "button"; b.dataset.action = a;
        b.onclick = () => startActivity(a);
        wrap.appendChild(b);
      });
      renderActivityStatus();
    }

    function renderActivityStatus() {
      const ready = readinessForDisplay();
      const st = document.getElementById("act-status");
      const stop = document.getElementById("actStop");
      const wrap = document.getElementById("activityBtns");
      const warn = document.getElementById("recWarn");
      const s = g_session, recording = !!(s && s.active);
      if (st) {
        if (recording) {
          const left = Math.max(0, Math.ceil((s.endAt - Date.now()) / 1000));
          st.textContent = "⏺ Recording '" + s.label + "' , " + left + "s left" +
            (s.labelled ? " (" + s.labelled + " clip" + (s.labelled > 1 ? "s" : "") + ")" : "");
          st.className = "msg ok";
        } else if (s) {
          st.textContent = "Saving '" + s.label + "'… " + (s.labelled || 0) + " clip(s)";
          st.className = "msg";
        } else if (g_forceOn) {
          st.textContent = "⏺ Force-capture is on , press Stop to end it.";
          st.className = "msg err";
        } else { st.textContent = ""; st.className = "msg"; }
      }
      if (stop) stop.style.display = (recording || (!s && g_forceOn)) ? "" : "none";
      if (warn) {
        if (!ready.ok && !recording) { warn.textContent = "⚠ " + ready.msg; warn.classList.remove("hidden"); }
        else warn.classList.add("hidden");
      }
      if (wrap) wrap.querySelectorAll("button").forEach(b => {
        b.disabled = recording || !ready.ok;   // can't record without a connected collar
        b.classList.toggle("primary", !!(s && b.dataset.action === s.label));
      });
      renderFocus(ready);
    }

    async function startActivity(label) {
      if (g_demo) return msg("act-msg", "Read-only demo , sign in with a dev account to make changes.", "err");
      if (g_session) return;   // already recording , Stop first
      const ready = recordReadiness();
      if (!ready.ok) { msg("act-msg", ready.msg, "err"); renderActivityStatus(); return; }
      const tokens = Object.entries(lastDevices).filter(([, d]) => d && d.type === "station").map(([t]) => t);
      if (!tokens.length) return msg("act-msg", "No stations to control.", "err");
      const secs = parseInt(document.getElementById("actSecs").value, 10) || 30;
      // remember the clips that already exist, so we only auto-label NEW ones
      const known = new Set();
      Object.values(lastDevices).forEach(d => { if (d && d.clips) Object.keys(d.clips).forEach(id => known.add(id)); });
      const now = Date.now();
      const sess = { label, id: "s" + now, tokens, known, active: true, secs, startMs: now,
                     endAt: now + secs * 1000, graceUntil: 0, labelled: 0, stopTimer: 0, tickTimer: 0 };
      const updates = {};
      tokens.forEach(t => { updates["users/" + g_uid + "/devices/" + t + "/config/captureForce"] = true; });
      try { await firebase.database().ref().update(updates); }
      catch (e) { return msg("act-msg", e.message || "Couldn't start recording.", "err"); }
      g_session = sess; g_forceOn = true; msg("act-msg", "");
      sess.tickTimer = setInterval(renderActivityStatus, 500);
      sess.stopTimer = setTimeout(() => stopActivity("auto"), secs * 1000);
      renderActivityButtons();
    }

    async function stopActivity(reason) {
      // No managed session, but force-capture may be left on , turn it off.
      if (!g_session) {
        if (g_forceOn && !g_demo) {
          const tokens = Object.entries(lastDevices).filter(([, d]) => d && d.type === "station").map(([t]) => t);
          const updates = {}; tokens.forEach(t => { updates["users/" + g_uid + "/devices/" + t + "/config/captureForce"] = false; });
          try { await firebase.database().ref().update(updates); g_forceOn = false; } catch (e) {}
          renderActivityStatus();
        }
        return;
      }
      const s = g_session;
      if (s.stopTimer) { clearTimeout(s.stopTimer); s.stopTimer = 0; }
      s.active = false;
      s.graceUntil = Date.now() + 15000;   // keep labelling late uploads for 15 s after stopping
      const updates = {};
      s.tokens.forEach(t => { updates["users/" + g_uid + "/devices/" + t + "/config/captureForce"] = false; });
      try { await firebase.database().ref().update(updates); g_forceOn = false; } catch (e) {}
      renderActivityStatus();
      setTimeout(() => {
        if (g_session === s) {
          if (s.tickTimer) clearInterval(s.tickTimer);
          g_session = null;
          renderActivityButtons();
          msg("act-msg", "Saved " + s.labelled + " clip" + (s.labelled === 1 ? "" : "s") + " as '" + s.label + "'.", s.labelled ? "ok" : "");
        }
      }, 15500);
    }

    // Auto-label clips that arrived during an active session. Called from renderClips on every update;
    // the `known` set and the start-time guard keep it from touching old or unrelated clips.
    function maybeLabelNewClips(devices) {
      const s = g_session;
      if (!s) return;
      if (!s.active && Date.now() > s.graceUntil) return;   // window closed
      const updates = {}; let n = 0;
      Object.entries(devices || {}).forEach(([token, d]) => {
        if (!d || d.type !== "station" || !d.clips) return;
        Object.entries(d.clips).forEach(([id, c]) => {
          if (s.known.has(id)) return;
          s.known.add(id);
          if (c && c.label) return;                                        // already labelled
          if (c && typeof c.ts === "number" && c.ts < s.startMs - 5000) return;   // captured before this session
          updates["users/" + g_uid + "/devices/" + token + "/clips/" + id + "/label"] = s.label;
          updates["users/" + g_uid + "/devices/" + token + "/clips/" + id + "/session"] = s.id;
          n++;
        });
      });
      if (n) {
        s.labelled += n;
        firebase.database().ref().update(updates).catch(e => console.error("auto-label failed:", e));
        renderActivityStatus();
      }
    }
    async function toggleCapture() {
      if (g_demo) { renderCapBtn(); return msg("cap-msg", "Read-only demo , sign in with a dev account to make changes.", "err"); }
      const next = document.getElementById("capToggle").checked;   // the switch's new position
      const tokens = Object.entries(lastDevices).filter(([, d]) => d && d.type === "station").map(([t]) => t);
      if (!tokens.length) { renderCapBtn(); return msg("cap-msg", "No stations to control.", "err"); }
      const updates = {};
      tokens.forEach(t => { updates["users/" + g_uid + "/devices/" + t + "/config/capture"] = next; });
      try {
        await firebase.database().ref().update(updates);
        g_captureOn = next; renderCapBtn();
        msg("cap-msg", next ? "On , clips will appear below within ~10 s when a collar's in range." : "Off.", "ok");
      } catch (e) {
        renderCapBtn();   // revert the switch , the write didn't land
        msg("cap-msg", e.message || "Failed.", "err");
      }
    }

    // ---- range config (written here, read by the station) ----
    function loadConfig() {
      const first = Object.values(lastDevices).find(d => d && d.type === "station" && d.config);
      if (first && first.config) {
        if (typeof first.config.rssiThreshold === "number") {
          document.getElementById("thr").value = first.config.rssiThreshold;
          document.getElementById("thrVal").textContent = first.config.rssiThreshold;
        }
        if (typeof first.config.dwellMs === "number") document.getElementById("dwell").value = first.config.dwellMs;
        g_captureOn = first.config.capture === true;
        g_forceOn = first.config.captureForce === true;
        g_production = first.config.mode === "production";
        renderCapBtn();
        renderActivityStatus();   // reflect leftover force-capture, if any
      }
    }
    async function saveConfig() {
      if (g_demo) return msg("cfg-msg", "Read-only demo , sign in with a dev account to make changes.", "err");
      const rssiThreshold = parseInt(document.getElementById("thr").value, 10);
      const dwellMs = parseInt(document.getElementById("dwell").value, 10) || 0;
      const tokens = Object.entries(lastDevices).filter(([, d]) => d && d.type === "station").map(([t]) => t);
      if (!tokens.length) return msg("cfg-msg", "No stations to configure.", "err");
      const updates = {};
      tokens.forEach(t => {
        updates["users/" + g_uid + "/devices/" + t + "/config/rssiThreshold"] = rssiThreshold;
        updates["users/" + g_uid + "/devices/" + t + "/config/dwellMs"] = dwellMs;
      });
      try { await firebase.database().ref().update(updates); msg("cfg-msg", "Saved to " + tokens.length + " station(s).", "ok"); }
      catch (e) { msg("cfg-msg", e.message || "Save failed.", "err"); }
    }
    function msg(id, t, k) { const e = document.getElementById(id); e.textContent = t || ""; e.className = "msg" + (k ? " " + k : ""); }

    // ---- read-only demo (?demo=1): load the demo owner's data without auth, every write disabled ----
    async function initDemo() {
      const demoUid = (await firebase.database().ref("config/demoOwner").once("value")).val();
      if (!demoUid) { document.getElementById("gateMsg").textContent = "Demo isn't configured yet."; return show("gate"); }
      g_uid = demoUid;
      document.body.classList.add("demo-readonly");
      const who = document.getElementById("who"); if (who) who.textContent = "Demo , read-only";
      const banner = document.getElementById("demoBanner"); if (banner) banner.classList.remove("hidden");
      attach(demoUid);
      show("dev");
    }

    // ---- auth + dev-account gate ----
    firebase.auth().onAuthStateChanged(async (user) => {
      if (g_demo) return;   // demo mode owns the view , don't let auth state override it
      if (devicesRef) { devicesRef.off(); devicesRef = null; }
      if (modelsRef) { modelsRef.off(); modelsRef = null; }
      if (actionsRef) { actionsRef.off(); actionsRef = null; }
      if (timer) { clearInterval(timer); timer = null; }
      if (!user) {
        document.getElementById("gateMsg").innerHTML = 'Please <a href="account.html">log in</a> with a dev account.';
        return show("gate");
      }
      g_uid = user.uid;
      const isDev = (await firebase.database().ref("config/devAccounts/" + user.uid).once("value")).val() === true;
      if (!isDev) {
        document.getElementById("gateMsg").textContent = "This account isn't a dev account.";
        return show("gate");
      }
      document.getElementById("who").textContent = user.email || "Dev";
      attach(user.uid);
      document.getElementById("delAll").onclick = deleteAllClips;
      show("dev");
    });

    // In demo mode, skip the auth gate entirely and load the showcase data on page load.
    if (g_demo) initDemo();
