/*
 * Audio/IMU streaming , the decoupled reader/sender pair. See streaming.h.
 *
 * CONTINUOUS streaming. While a central is subscribed we keep the mic running and send the audio in
 * 100 ms frames, each carrying the IMU sampled alongside it, over one persistent connection. The
 * station concatenates frames and slices them into fixed clips (50 frames = 5 s). No per-clip connect/
 * disconnect, so there's no gap between clips , we don't miss data while the cat's at the bowl.
 *
 * Each frame on the wire is [hdr][audio µ-law][IMU int16]. The header (struct meow_clip_hdr) +
 * MEOW_CLIP_MAGIC are defined once in firmware/common/meow_protocol.h and shared with the station,
 * so the wire format can't drift between the two.
 */
#include "streaming.h"
#include "ble.h"
#include "audio.h"
#include "imu.h"

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <string.h>

#include "meow_protocol.h"   /* meow_clip_hdr + MEOW_CLIP_MAGIC , the shared wire format */

LOG_MODULE_REGISTER(streaming, LOG_LEVEL_INF);

#define FRAME_IMU_VALS_MAX  ((IMU_RATE_HZ / 10 + 6) * IMU_AXES)   /* IMU int16 per 100 ms, with margin */

/* One wire frame: [hdr][audio µ-law][IMU int16]. The reader builds these; the sender drains them. */
#define FRAME_BYTES  (sizeof(struct meow_clip_hdr) + MIC_BLOCK_BYTES + FRAME_IMU_VALS_MAX * 2)
struct tx_frame { uint16_t len; uint8_t data[FRAME_BYTES]; };

/* Reader -> sender hand-off. The reader (mic) MUST never wait on BLE: if it blocked on a slow link
 * the PDM DMA would overrun and the mic would restart, ringing out as an audible pop. So the reader
 * drains the mic every 100 ms into this queue and moves on; a separate sender thread pushes frames
 * to BLE at whatever rate the link allows. If the link falls behind and the queue fills, the reader
 * drops the OLDEST frame (a tiny audio gap) , far better than starving the mic. ~24 frames = ~2.4 s
 * of slack, so normal BLE jitter never drops anything. */
#define TX_QUEUE_FRAMES 24
K_MSGQ_DEFINE(tx_q, sizeof(struct tx_frame), TX_QUEUE_FRAMES, 4);

/* SENDER: pop a frame and notify it over BLE. Blocking here is fine , it never touches the mic. */
static void tx_thread(void *a, void *b, void *c)
{
    ARG_UNUSED(a); ARG_UNUSED(b); ARG_UNUSED(c);
    static struct tx_frame fr;
    while (1) {
        if (k_msgq_get(&tx_q, &fr, K_FOREVER) != 0) continue;
        if (!ble_streaming_enabled()) continue;   /* discard frames left over around a disconnect */
        ble_notify_frame(fr.data, fr.len);        /* best-effort; on error the frame is just dropped */
    }
}
K_THREAD_DEFINE(tx_tid, 4096, tx_thread, NULL, NULL, NULL, 7, 0, 0);

/* READER: drive the mic and the IMU, build frames, enqueue them. Never blocks on BLE. */
static void stream_thread(void *a, void *b, void *c)
{
    ARG_UNUSED(a); ARG_UNUSED(b); ARG_UNUSED(c);
    static struct tx_frame fr, discard;
    while (1) {
        if (!ble_streaming_enabled() || !audio_mic_ready()) { k_sleep(K_MSEC(100)); continue; }

        if (audio_trigger_start() < 0) { k_sleep(K_MSEC(200)); continue; }
        audio_stream_start();                 /* settle the PDM filter once, then sample continuously */
        k_msgq_purge(&tx_q);                  /* drop any frames left from a previous session */
        imu_stream_start();
        LOG_INF("streaming started");

        uint32_t q_peak = 0, dropped = 0;     /* health: queue high-water + frames dropped (BLE behind) */
        int health_ct = 0;

        while (ble_streaming_enabled()) {
            uint8_t *fp = fr.data + sizeof(struct meow_clip_hdr);

            int n = audio_read_ulaw(fp, MIC_BLOCK_BYTES);
            if (n < 0) break;                            /* mic read error , restart the session */
            uint32_t audio_bytes = (uint32_t)n;

            size_t iv = imu_drain((int16_t *)(fp + audio_bytes), FRAME_IMU_VALS_MAX);
            uint32_t imu_bytes = (uint32_t)iv * 2;
            static int dry_frames;
            if (iv == 0) {
                if (++dry_frames == 20) LOG_WRN("IMU drained 0 samples for 2 s , sensor not producing data");
            } else if (dry_frames) {
                dry_frames = 0;
            }

            struct meow_clip_hdr hdr = {
                .magic = MEOW_CLIP_MAGIC, .version = 2,   /* v2 = audio is 8-bit µ-law */
                .imu_axes = IMU_AXES, .imu_rate_hz = IMU_RATE_HZ,
                .audio_bytes = audio_bytes, .imu_bytes = imu_bytes, .audio_rate = MIC_RATE,
            };
            memcpy(fr.data, &hdr, sizeof hdr);
            fr.len = (uint16_t)(sizeof hdr + audio_bytes + imu_bytes);

            /* Hand off to the sender. If the queue is full the link is behind , drop the oldest frame
             * to keep the newest audio flowing (a small gap, not a mic-starving pop). */
            if (k_msgq_put(&tx_q, &fr, K_NO_WAIT) != 0) {
                k_msgq_get(&tx_q, &discard, K_NO_WAIT);
                k_msgq_put(&tx_q, &fr, K_NO_WAIT);
                dropped++;
            }
            uint32_t qd = k_msgq_num_used_get(&tx_q);
            if (qd > q_peak) q_peak = qd;
            if (++health_ct >= 50) {   /* ~every 5 s */
                LOG_INF("audio health: tx queue peak %u/%u, dropped %u frames (0 = BLE keeping up)",
                        q_peak, TX_QUEUE_FRAMES, dropped);
                q_peak = 0; dropped = 0; health_ct = 0;
            }
        }

        imu_stream_stop();
        audio_stream_stop();
        LOG_INF("streaming stopped");
    }
}
K_THREAD_DEFINE(stream_tid, 4096, stream_thread, NULL, NULL, NULL, 6, 0, 0);
