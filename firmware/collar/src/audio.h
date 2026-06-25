/*
 * Onboard PDM microphone (XIAO Sense) , capture + model-rate conversion.
 *
 * Captures at the PDM's real 16 kHz, decimates 2:1 to 8 kHz, and µ-law-encodes to one byte per
 * sample , the exact representation the model trains on and the stream sends. The streaming reader
 * drives start/stop and pulls one 100 ms chunk per frame; everything PDM-specific stays here.
 */
#pragma once
#include <stdint.h>
#include <stdbool.h>

#define MIC_RATE        8000                          /* wire/output rate (what we send + label) */
#define MIC_BLOCK_BYTES (2 * (MIC_RATE / 10))         /* 100 ms @ 8 kHz, 16-bit = one wire frame */

/* Configure the PDM mic. Safe to call once at boot; sets the ready flag on success. */
void audio_mic_init(void);

/* True once the mic is configured and can be triggered. */
bool audio_mic_ready(void);

/* Start the PDM hardware. Returns 0 on success (non-zero = trigger failed, caller should retry). */
int audio_trigger_start(void);

/* Discard a few blocks so the decimation/PDM filter settles once (avoids the start-of-stream
 * click). Call after a successful audio_trigger_start(), before the first audio_read_ulaw(). */
void audio_stream_start(void);

/* End the capture session (stop the PDM). */
void audio_stream_stop(void);

/* Read the next 100 ms of audio as 8 kHz µ-law (one byte per sample): blocks for one DMA block at
 * 16 kHz, decimates 2:1, and µ-law-encodes into dst. Returns the number of µ-law bytes written, or
 * -1 on a read error (the caller should end the session). dst must hold MIC_BLOCK_BYTES/2 bytes. */
int audio_read_ulaw(uint8_t *dst, uint32_t max_bytes);
