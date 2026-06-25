/*
 * Onboard PDM microphone (XIAO Sense) , capture + model-rate conversion. See audio.h.
 *
 * Captures short clips for eat/drink labelling. 8 kHz is plenty for crunch vs lap and halves the
 * BLE data, so clips are small and transfer fast (lets us record back-to-back with no gap).
 *
 * The nRF52840 PDM block CANNOT produce 8 kHz natively: its slowest clock (~1 MHz / 64 decimation)
 * floors at ~15.6 kHz, so asking the driver for 8 kHz silently yields ~16 kHz (configure still
 * "succeeds"). That made clips play back at half speed and doubled the link throughput (the click).
 * So we capture at the real 16 kHz and decimate 2:1 in software (pairwise average = a cheap
 * anti-alias low-pass) to a genuine 8 kHz wire stream.
 */
#include "audio.h"
#include "audio_codec.h"   /* ulaw_encode , shared with the inference preprocessing */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/audio/dmic.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(audio, LOG_LEVEL_INF);

#define MIC_CAP_RATE    16000                         /* PDM hardware native rate (decimated 2:1) */
#define MIC_BITS        16
#define MIC_CAP_BYTES   (2 * (MIC_CAP_RATE / 10))     /* 100 ms @ 16 kHz = one DMA block */

/* The reader thread drains this every 100 ms straight into the TX queue and never blocks on BLE, so
 * the slab stays near-empty , a few blocks of jitter headroom is plenty (the BLE backlog now lives
 * in the much larger tx_q instead). 8 blocks = ~0.8 s, and freeing the old deep slab leaves RAM for
 * the frame queue. */
#define MIC_BLOCKS      8
K_MEM_SLAB_DEFINE_STATIC(mic_slab, MIC_CAP_BYTES, MIC_BLOCKS, 4);
static const struct device *mic_dev = DEVICE_DT_GET(DT_NODELABEL(dmic_dev));
static bool g_mic_ready = false;

void audio_mic_init(void)
{
    if (!device_is_ready(mic_dev)) { LOG_ERR("mic not ready"); return; }
    struct pcm_stream_cfg stream = { .pcm_width = MIC_BITS, .mem_slab = &mic_slab };
    struct dmic_cfg cfg = {
        .io = { .min_pdm_clk_freq = 1000000, .max_pdm_clk_freq = 3500000,
                .min_pdm_clk_dc = 40, .max_pdm_clk_dc = 60 },
        .streams = &stream,
        .channel = { .req_num_streams = 1, .req_num_chan = 1 },
    };
    cfg.channel.req_chan_map_lo = dmic_build_channel_map(0, 0, PDM_CHAN_LEFT);
    cfg.streams[0].pcm_rate = MIC_CAP_RATE;        /* native 16 kHz; decimated to MIC_RATE on read */
    cfg.streams[0].block_size = MIC_CAP_BYTES;
    if (dmic_configure(mic_dev, &cfg) < 0) { LOG_ERR("dmic configure failed"); return; }
    g_mic_ready = true;
    LOG_INF("mic ready");
}

bool audio_mic_ready(void) { return g_mic_ready; }

void audio_stream_start(void)
{
    /* settle the PDM filter ONCE at stream start (avoids the click) by discarding a few blocks. */
    for (int skip = 0; skip < 4; skip++) {
        void *sb; uint32_t sz;
        if (dmic_read(mic_dev, 0, &sb, &sz, 500) >= 0) k_mem_slab_free(&mic_slab, sb);
    }
}

/* Start the PDM. Returns the dmic_trigger result (0 = ok). Kept separate from audio_stream_start so
 * the reader can bail before the settle-skip if the trigger fails. */
int audio_trigger_start(void)
{
    return dmic_trigger(mic_dev, DMIC_TRIGGER_START);
}

void audio_stream_stop(void)
{
    dmic_trigger(mic_dev, DMIC_TRIGGER_STOP);
}

int audio_read_ulaw(uint8_t *dst, uint32_t max_bytes)
{
    void *buf; uint32_t size;
    if (dmic_read(mic_dev, 0, &buf, &size, 500) < 0) return -1;

    /* Decimate 2:1 (16 kHz -> 8 kHz) out of the DMA slab, then µ-law encode to 8-bit so each
     * sample is one byte (half the wire data). Averaging adjacent samples is a cheap
     * anti-alias low-pass. Free the slab IMMEDIATELY once read. */
    if (size > MIC_CAP_BYTES) size = MIC_CAP_BYTES;
    const int16_t *src = (const int16_t *)buf;
    uint32_t out_n = (size / 2) / 2;                 /* 16 kHz samples / 2 -> 8 kHz */
    if (out_n > max_bytes) out_n = max_bytes;
    for (uint32_t i = 0; i < out_n; i++) {
        int16_t s = (int16_t)(((int32_t)src[2 * i] + src[2 * i + 1]) / 2);
        dst[i] = ulaw_encode(s);                     /* 16-bit PCM -> 8-bit µ-law */
    }
    k_mem_slab_free(&mic_slab, buf);
    return (int)out_n;                               /* one µ-law byte per sample */
}
