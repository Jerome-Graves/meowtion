/*
 * Meowtion BLE wire protocol , the contract between the collar and the station.
 *
 * SINGLE SOURCE OF TRUTH: both firmwares include this one header (firmware/common is on each build's
 * include path). The collar (Zephyr) and the station (ESP-IDF) are separate builds, so this is the
 * one place the on-the-wire format is defined , change it here and both sides stay in sync.
 *
 * While a station is subscribed, the collar streams continuously in 100 ms frames on the audio
 * characteristic. Each frame is:
 *
 *     [ meow_clip_hdr ][ audio payload ][ IMU payload ]
 *
 * The station concatenates frames and slices them into fixed-length training clips.
 */
#pragma once
#include <stdint.h>

#define MEOW_CLIP_MAGIC 0x574F454Du   /* 'M''E''O''W' little-endian , marks each frame's start */

/* Per-frame header. `version` selects the audio encoding:
 *   1 = audio payload is 16-bit PCM
 *   2 = audio payload is 8-bit G.711 µ-law (half the bytes; station expands it back to PCM) */
struct __attribute__((packed)) meow_clip_hdr {
	uint32_t magic;
	uint8_t  version;
	uint8_t  imu_axes;      /* 6 = accel x/y/z + gyro x/y/z */
	uint16_t imu_rate_hz;
	uint32_t audio_bytes;   /* audio payload size after the header (one 100 ms frame) */
	uint32_t imu_bytes;     /* IMU payload size after the audio */
	uint32_t audio_rate;    /* output sample rate, for the station's WAV header */
};
typedef struct meow_clip_hdr meow_clip_hdr_t;

/* G.711 µ-law codec. The collar encodes (16-bit -> 8-bit) to halve the BLE data; the station decodes
 * back to 16-bit PCM for a normal WAV. Standard telephony companding , clean for speech-like audio. */
static inline uint8_t ulaw_encode(int16_t pcm)
{
	const int BIAS = 0x84, CLIP = 32635;
	int sign = (pcm >> 8) & 0x80;
	/* Take the magnitude in a WIDER int: negating -32768 as int16 overflows back to -32768, which
	 * mis-encodes a full-scale-negative sample to near-silence. In int it negates cleanly. */
	int mag = sign ? -(int)pcm : pcm;
	if (mag > CLIP) mag = CLIP;
	mag += BIAS;
	int exponent = 7;
	for (int mask = 0x4000; (mag & mask) == 0 && exponent > 0; mask >>= 1) exponent--;
	int mantissa = (mag >> (exponent + 3)) & 0x0F;
	return (uint8_t)~(sign | (exponent << 4) | mantissa);
}

static inline int16_t ulaw_decode(uint8_t u)
{
	u = (uint8_t)~u;
	int sign = u & 0x80, exponent = (u >> 4) & 0x07, mantissa = u & 0x0F;
	int sample = (((mantissa << 3) + 0x84) << exponent) - 0x84;
	return (int16_t)(sign ? -sample : sample);
}
