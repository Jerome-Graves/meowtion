/*
 * Audio representation shared by training-data capture and on-collar inference , the single source
 * of truth so the two can never drift apart.
 *
 * Training clips travel: PDM 16 kHz -> decimate 2:1 to 8 kHz -> µ-law (8-bit) over BLE -> the station
 * decodes µ-law back to 16-bit PCM and stores a WAV. So the audio-confirm model trains on 8 kHz audio
 * that has been through a µ-law round-trip.
 *
 * For the on-collar audio stage (clf_classify, stage 2) to see the SAME distribution at inference as
 * it saw in training, run live mic audio through audio_to_model_pcm() before handing it to the
 * cascade. A train/inference representation mismatch costs far more accuracy than the µ-law noise
 * floor itself, so everything funnels through here.
 */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include "meow_protocol.h"   /* ulaw_encode/ulaw_decode + the wire format , shared with the station */

#define MODEL_AUDIO_RATE_HZ 8000   /* the rate the audio model trains and infers at */

/*
 * Convert a raw 16 kHz PDM window to the model's audio representation: 8 kHz, µ-law-companded 16-bit,
 * i.e. EXACTLY what a training clip became. Decimate 2:1 (pairwise average = a cheap anti-alias
 * low-pass), then a µ-law encode+decode round-trip to impose the same 8-bit quantization the training
 * audio carries. Writes up to out_cap samples to out8k; returns the number of 8 kHz samples produced.
 *
 *   in16k / in_n : raw 16 kHz int16 samples captured live on the collar
 *   out8k        : model-ready 8 kHz int16 samples (pass to clf_classify as pcm/pcm_len)
 */
static inline size_t audio_to_model_pcm(const int16_t *in16k, size_t in_n,
                                        int16_t *out8k, size_t out_cap)
{
	size_t out_n = in_n / 2;
	if (out_n > out_cap) out_n = out_cap;
	for (size_t i = 0; i < out_n; i++) {
		int16_t s = (int16_t)(((int32_t)in16k[2 * i] + in16k[2 * i + 1]) / 2);
		out8k[i] = ulaw_decode(ulaw_encode(s));   /* same 8-bit µ-law quantization as training */
	}
	return out_n;
}
