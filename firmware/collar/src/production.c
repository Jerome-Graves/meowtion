/*
 * Production-mode on-device classification. See production.h for the telemetry contract.
 *
 * Each cycle we:
 *   1. Keep the IMU sampling continuously (imu_stream_start once, only when NOT in a capture stream
 *      , the capture path in streaming.c owns the IMU while it runs, so we never start it then).
 *   2. Drain the newest IMU samples and slide them into a rolling keep-last window of the most
 *      recent IMU_RATE_HZ (104) frames x IMU_AXES, presented as imu_features_t to the cascade.
 *   3. Accrue steps from IMU motion (accel-magnitude threshold crossings), matching the spirit of
 *      the simulated path so the step counter keeps climbing.
 *   4. r = clf_classify(&feat, pcm, pcm_len) and write the version=2 packet.
 *
 * AUDIO CONFIRM (cascade stage 2): when the IMU stage returns a candidate class but is uncertain
 * (confidence below the cascade threshold) and an audio model is present, we capture a 1 s live audio
 * window and let the cascade's audio stage confirm/correct it (the eat-vs-drink case). audio.c
 * already emits the model's exact training representation , decimate 16->8 kHz then µ-law , so we read
 * that µ-law stream (audio_read_ulaw) and decode it straight back to int16. That is bit-identical to
 * audio_to_model_pcm() and to what a training clip became, so no raw-16 kHz-PCM path is needed. A
 * confident IMU result skips the mic entirely, so audio only costs power when it is actually needed.
 * Production runs only when NOT in a capture stream (production_active()), so the PDM mic is free , the
 * capture reader in streaming.c is idle , and we still bail if a stream preempts us mid-window.
 */
#include "production.h"

#include "classifier.h"
#include "imu.h"
#include "ble.h"
#include "battery.h"
#include "audio.h"
#include "audio_codec.h"   /* MODEL_AUDIO_RATE_HZ + ulaw_decode (via meow_protocol.h) */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <math.h>
#include <string.h>

LOG_MODULE_REGISTER(production, LOG_LEVEL_INF);

/* Rolling window: the most recent IMU_RATE_HZ frames x IMU_AXES, kept "last N". */
#define WIN_FRAMES  IMU_RATE_HZ
#define WIN_VALS    (WIN_FRAMES * IMU_AXES)
static int16_t g_win[WIN_VALS];
static size_t  g_win_fill;          /* valid int16 in g_win (grows to WIN_VALS, then stays full) */

/* Scratch for one cycle's freshly-drained samples. Bounded by what ~2 s at 104 Hz can produce;
 * size it for a full window so a burst can't overflow (extra is just discarded oldest-first). */
static int16_t g_drain[WIN_VALS];

static bool     g_imu_started;      /* did WE start the IMU (production), vs the capture path */
static uint16_t g_steps;            /* mirror of the telemetry step count, accrued from motion */
static uint32_t g_peak_mg;          /* peak |accel|-1g (mg) this cycle, for the activity gate */

/* simple step detection: count accel-magnitude crossings above a threshold, with a refractory gap
 * so one stride isn't counted many times. Tuned loosely , this is a motion-activity proxy, not a
 * pedometer. accel is milli-g; ~1000 mg = gravity at rest. */
#define STEP_MG_THRESH  1400        /* magnitude above this (well over 1g) = a motion event */
#define STEP_REFRACTORY 3           /* min frames between counted steps */

bool production_active(void)
{
    /* PRODUCTION: a trained IMU model is linked AND we are not in a capture/training stream. */
    return clf_imu_model_present() && !ble_streaming_enabled();
}

uint32_t production_peak_mg(void) { return g_peak_mg; }

/* Peak accel-magnitude deviation from 1 g (mg) over freshly-drained frames. The activity gate uses
 * this to decide active vs still. Tracks the max squared magnitude then takes one sqrt at the end. */
static void update_peak_mg(const int16_t *src, size_t n)
{
    uint32_t max2 = 0;
    for (size_t i = 0; i + IMU_AXES <= n; i += IMU_AXES) {
        int32_t ax = src[i], ay = src[i + 1], az = src[i + 2];   /* milli-g */
        /* Each square <= 32767^2 (fits int32); sum in uint32_t (<= 3*32767^2 < UINT32_MAX), so the
         * accumulation can't overflow even at full-scale impact. */
        uint32_t mag2 = (uint32_t)(ax * ax) + (uint32_t)(ay * ay) + (uint32_t)(az * az);
        if (mag2 > max2) max2 = mag2;
    }
    if (n < IMU_AXES) { g_peak_mg = 0; return; }                  /* no samples this cycle */
    double dev = sqrt((double)max2) - 1000.0;
    g_peak_mg = (uint32_t)(dev < 0.0 ? -dev : dev);
}

/* Slide `n` int16 (whole frames) from src into the end of the rolling window, dropping the oldest. */
static void window_push(const int16_t *src, size_t n)
{
    if (n == 0) return;
    if (n >= WIN_VALS) {
        /* more than a full window arrived: keep only the newest WIN_VALS */
        memcpy(g_win, src + (n - WIN_VALS), WIN_VALS * sizeof(int16_t));
        g_win_fill = WIN_VALS;
        return;
    }
    if (g_win_fill + n > WIN_VALS) {
        size_t shift = g_win_fill + n - WIN_VALS;          /* how much to drop off the front */
        memmove(g_win, g_win + shift, (g_win_fill - shift) * sizeof(int16_t));
        g_win_fill -= shift;
    }
    memcpy(g_win + g_win_fill, src, n * sizeof(int16_t));
    g_win_fill += n;
}

/* Accrue steps from the freshly-drained frames (interleaved [ax,ay,az,gx,gy,gz], accel in mg). */
static void accrue_steps(const int16_t *src, size_t n)
{
    static int refractory;
    for (size_t i = 0; i + IMU_AXES <= n; i += IMU_AXES) {
        int32_t ax = src[i], ay = src[i + 1], az = src[i + 2];
        /* integer magnitude, avoids float in the hot loop; square per-axis (fits int32) then sum in
         * uint32_t so a full-scale impact can't overflow */
        uint32_t mag2 = (uint32_t)(ax * ax) + (uint32_t)(ay * ay) + (uint32_t)(az * az);
        uint32_t thr2 = (uint32_t)STEP_MG_THRESH * STEP_MG_THRESH;
        if (refractory > 0) { refractory--; continue; }
        if (mag2 > thr2) { g_steps++; refractory = STEP_REFRACTORY; }
    }
}

void production_yield(void)
{
    /* If WE started the IMU, stop it so the capture path (or a clean re-entry) is unambiguous.
     * Only stop when no capture stream is running , if a stream took over, it owns stop/start. */
    if (g_imu_started && !ble_streaming_enabled()) {
        imu_stream_stop();
    }
    g_imu_started = false;
    g_win_fill = 0;
}

/* Capture one live 8 kHz audio window for the cascade's audio-confirm stage, in the model's exact
 * training representation. audio.c decimates 16->8 kHz and µ-law-encodes (the same transform training
 * clips go through), so decoding that µ-law stream back to int16 is bit-identical to
 * audio_to_model_pcm(). Drives the PDM directly (safe: production runs only when not streaming).
 * Returns the number of int16 samples written (<= cap), or 0 on failure / if a capture stream starts.
 * The 16 KiB buffer is static , RAM is tight, so this MUST be re-checked on hardware with real models. */
static int16_t g_audio_pcm[MODEL_AUDIO_RATE_HZ];

static size_t capture_audio_window(int16_t *out, size_t cap)
{
    if (!audio_mic_ready() || audio_trigger_start() < 0) {
        return 0;
    }
    audio_stream_start();                   /* settle the PDM filter once (discards a few blocks) */

    uint8_t ulaw[MIC_BLOCK_BYTES / 2];      /* one 100 ms block of 8 kHz µ-law (one byte per sample) */
    size_t got = 0;
    while (got < cap && !ble_streaming_enabled()) {   /* stop if a capture stream preempts the mic */
        int n = audio_read_ulaw(ulaw, sizeof ulaw);
        if (n < 0) break;                             /* mic read error , end the window */
        for (int i = 0; i < n && got < cap; i++) {
            out[got++] = ulaw_decode(ulaw[i]);        /* 8-bit µ-law -> int16, the training rep */
        }
    }
    audio_stream_stop();
    return got;
}

void production_update_telemetry(void)
{
    /* 1. Ensure the IMU is sampling. Only WE start it, and only when not in a capture stream , the
     * capture path (streaming.c) calls imu_stream_start/stop itself and owns the ring while active.
     * If a capture is running, production_active() is false and we are not called. */
    if (!g_imu_started) {
        imu_stream_start();
        g_imu_started = true;
        g_win_fill = 0;
    }

    /* 2. Drain everything available since last cycle and slide it into the rolling window. */
    size_t got = imu_drain(g_drain, WIN_VALS);
    accrue_steps(g_drain, got);
    update_peak_mg(g_drain, got);       /* motion-energy proxy for the rules-based activity gate */
    window_push(g_drain, got);

    /* 3. Present the latest 104 frames. If we don't yet have a full window (just entered production),
     * pass what we have , the IMU stage handles a short/empty window by returning UNKNOWN. */
    imu_features_t feat = {
        .samples = g_win,
        .count   = g_win_fill,
        .rate_hz = IMU_RATE_HZ,
        .axes    = IMU_AXES,
    };

    /* 4. Classify. IMU stage first (cheap, always). If it returned a candidate class but is uncertain
     * and an audio model is present, capture a live 8 kHz window and re-run so the cascade's audio
     * stage can confirm/correct it. A confident IMU result (or no audio model) skips the mic. */
    clf_result_t r = clf_classify(&feat, NULL, 0);
    if (clf_audio_model_present() && r.cls != CLF_UNKNOWN &&
        r.confidence < clf_get_config()->conf_threshold) {
        size_t n = capture_audio_window(g_audio_pcm, MODEL_AUDIO_RATE_HZ);
        if (n > 0) {
            r = clf_classify(&feat, g_audio_pcm, n);   /* IMU + audio confirm */
        }
    }

    /* Write the production telemetry packet per the contract (production.h). */
    uint8_t *mfg = ble_mfg_data();
    mfg[2] = 2;                                                  /* version 2 = real classification */
    mfg[3] = (r.cls >= 0) ? (uint8_t)r.cls : 0xFF;              /* class index, or 0xFF = UNKNOWN */
    int conf = (int)lroundf(r.confidence * 100.0f);             /* 0..100 */
    if (conf < 0) conf = 0; else if (conf > 100) conf = 100;
    mfg[4] = (uint8_t)conf;
    mfg[5] = g_steps & 0xFF;
    mfg[6] = (g_steps >> 8) & 0xFF;
    mfg[7] = read_battery();

    LOG_INF("production: cls=%d conf=%d%% steps=%u (win=%u/%u)",
            r.cls, conf, g_steps, (unsigned)g_win_fill, (unsigned)WIN_VALS);
}
