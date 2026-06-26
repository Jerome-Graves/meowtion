/*
 * dev.js - Meowtion developer console (dev-account gated).
 * Live station status, capture and mode toggles, the action set, cloud retraining,
 * and clip review (waveform, trim, delete).
 * Loaded after firebase-config.js, the Firebase compat SDKs, and firebase-init.js.
 */

    let g_uid = null;
    const g_demo = new URLSearchParams(location.search).has("demo");   // ?demo=1 => public read-only showcase
    let g_actions = ["eat", "drink", "purr"];   // user-defined action set (any pet behaviour), from users/<uid>/actions
    let devicesRef = null, modelsRef = null, actionsRef = null, lastDevices = {}, timer = null, lastClipsSig = "";
    let clipEls = {};   // clip id -> {row}; tracks rows already drawn so renderClips only adds/removes, never rebuilds

    function show(which) {
      document.getElementById("gate").classList.toggle("hidden", which !== "gate");
      document.getElementById("devview").classList.toggle("hidden", which !== "dev");
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

        // proximity / recording state reported by the station
        const state = dev.state || "idle";
        const cls = state === "recording" ? "p-rec blink" : state === "inRange" ? "p-on"
                  : state === "approaching" ? "p-near" : "p-idle";
        const txt = state === "recording" ? "● recording" : state === "inRange" ? "in range"
                  : state === "approaching" ? "settling…" : "idle";
        const badge = el("span", "pill " + cls, txt);
        const bWrap = el("div", "row"); bWrap.style.marginTop = ".6rem"; bWrap.appendChild(badge);
        if (dev.nearCollar) bWrap.appendChild(el("span", "muted", dev.nearCollar));
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
      const imu = el("span", "imu-badge" + (hasImu ? "" : " no"), hasImu ? "IMU ✓" : "audio only");
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
        stack.appendChild(lane(accelCv, "accel x·y·z"));
        if (imuAxes >= 6) { gyroCv = el("canvas", "wave-imu"); stack.appendChild(lane(gyroCv, "gyro x·y·z")); }
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
        lg.innerHTML = '<span><i style="background:#d1495b"></i>X</span>' +
                       '<span><i style="background:#2a9d8f"></i>Y</span>' +
                       '<span><i style="background:#5b6cc2"></i>Z</span>';
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
      if (!confirm("Delete ALL " + all.length + " clips and their audio/IMU files?\nThis cannot be undone.")) return;
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

    // Incremental: only ADD new clips (prepend) and REMOVE deleted ones; never touch existing rows.
    // Rebuilding the whole list recreated every <audio> on each new clip , that's what caused the
    // flashing and constant re-downloading.
    function renderClips(devices) {
      const wrap = document.getElementById("clips");
      const all = [];
      Object.entries(devices || {}).forEach(([token, d]) => {
        if (d && d.type === "station" && d.clips)
          Object.entries(d.clips).forEach(([id, c]) => all.push({ id, token, ...c }));
      });
      all.sort((a, b) => (b.ts || 0) - (a.ts || 0));
      const visible = all.slice(0, 200);                // rows are cheap now (collapsed, no audio), so show plenty
      const inView = {};
      visible.forEach(c => { inView[c.id] = c; });
      // remove rows that are gone OR fell past the newest-200 (and DON'T re-add them , that loop was the bug)
      Object.keys(clipEls).forEach(id => { if (!inView[id]) { clipEls[id].row.remove(); delete clipEls[id]; } });
      if (!visible.length) { wrap.innerHTML = '<div class="empty">No clips yet.</div>'; clipEls = {}; return; }
      const emp = wrap.querySelector(".empty"); if (emp) emp.remove();
      // oldest -> newest of the visible set, prepend each so the newest ends up on top
      visible.slice().reverse().forEach(c => {
        if (!clipEls[c.id]) {
          const row = buildClipRow(c);
          clipEls[c.id] = { row };
          wrap.insertBefore(row, wrap.firstChild);
        }
      });
    }

    function renderAll() {
      try { renderStations(lastDevices); } catch (e) { console.error("renderStations failed:", e); }
      try { renderClips(lastDevices); } catch (e) { console.error("renderClips failed:", e); }
    }

    function attach(uid) {
      devicesRef = firebase.database().ref("users/" + uid + "/devices");
      devicesRef.on("value", s => { lastDevices = s.val() || {}; renderAll(); loadConfig(); });
      modelsRef = firebase.database().ref("users/" + uid + "/models");
      modelsRef.on("value", s => renderModels(s.val()));   // live cloud-training status
      actionsRef = firebase.database().ref("users/" + uid + "/actions");
      actionsRef.on("value", s => {
        const a = s.val();
        g_actions = (Array.isArray(a) && a.length) ? a : ["eat", "drink", "purr"];
        renderActions();
        // refresh clip dropdowns so new actions appear as options
        Object.keys(clipEls).forEach(id => { clipEls[id].row.remove(); delete clipEls[id]; });
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
      document.getElementById("forceToggle").checked = g_forceOn;
      document.getElementById("forceState").textContent = g_forceOn ? "On" : "Off";
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
    async function toggleForce() {
      if (g_demo) { renderCapBtn(); return msg("force-msg", "Read-only demo , sign in with a dev account to make changes.", "err"); }
      const next = document.getElementById("forceToggle").checked;
      const tokens = Object.entries(lastDevices).filter(([, d]) => d && d.type === "station").map(([t]) => t);
      if (!tokens.length) { renderCapBtn(); return msg("force-msg", "No stations to control.", "err"); }
      const updates = {};
      tokens.forEach(t => { updates["users/" + g_uid + "/devices/" + t + "/config/captureForce"] = next; });
      try {
        await firebase.database().ref().update(updates);
        g_forceOn = next; renderCapBtn();
        msg("force-msg", next ? "On , recording whenever the collar is heard, any distance." : "Off.", "ok");
      } catch (e) {
        renderCapBtn();   // revert the switch , the write didn't land
        msg("force-msg", e.message || "Failed.", "err");
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
