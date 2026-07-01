/* Host fuzz + differential tests for the mu-law codec and the model-input audio representation.
 * Pure headers only (firmware/common/meow_protocol.h + collar/src/audio_codec.h), no Zephyr, no
 * hardware. See firmware/test/Makefile.
 *
 *   make -C firmware/test check
 *
 * These apply the property/fuzz method to the collar-side C: encode each codec invariant, then sweep
 * the WHOLE int16 domain exhaustively (only 65536 values , cheaper and more thorough than sampling),
 * and fuzz audio_to_model_pcm over seeded-random windows. The final test is a DIFFERENTIAL check that
 * pins the claim that the collar's training wire representation and its inference representation are
 * the exact same samples.
 */
#include <stdint.h>
#include <stdio.h>

#include "audio_codec.h"    /* audio_to_model_pcm + (via meow_protocol.h) ulaw_encode/ulaw_decode */
#include "test_util.h"

/* deterministic PRNG (xorshift32) so any failure is reproducible from the printed counterexample */
static uint32_t g_rng = 0x9E3779B9u;
static uint32_t xr(void) { g_rng ^= g_rng << 13; g_rng ^= g_rng >> 17; g_rng ^= g_rng << 5; return g_rng; }
static int16_t rnd16(void) { return (int16_t)(xr() & 0xFFFFu); }


/* ---- mu-law codec, exhaustive over the domain ---------------------------------------------- */

/* Decoding a byte then re-encoding must return the same byte (the codec's level table is
 * self-consistent). The two zero codes 0x7F (-0) and 0xFF (+0) both decode to 0 and canonicalise to
 * one on re-encode , that G.711 aliasing is expected, so bytes that decode to 0 are exempt. */
static void test_ulaw_byte_roundtrip_consistent(void)
{
	int bad = -1;
	for (int b = 0; b < 256; b++) {
		int16_t d = ulaw_decode((uint8_t)b);
		if (d != 0 && ulaw_encode(d) != (uint8_t)b) { bad = b; break; }
	}
	CHECK(bad < 0, "ulaw encode(decode(b)) == b for every non-zero-aliased byte");
	if (bad >= 0) printf("    counterexample: byte 0x%02X\n", bad);
}

/* A clearly non-zero sample must keep its sign through the codec , it must not collapse to ~0. This
 * is where the classic INT16_MIN bug hides: negating -32768 as int16 overflows back to -32768. */
static void test_ulaw_preserves_sign(void)
{
	int bad = 0, bs = 0, bd = 0;
	for (int s = -32768; s <= 32767; s++) {
		if (s > -256 && s < 256) continue;                 /* near zero, quantizing to 0 is fine */
		int16_t d = ulaw_decode(ulaw_encode((int16_t)s));
		if ((d < 0) != (s < 0) || d == 0) { bad = 1; bs = s; bd = d; break; }
	}
	CHECK(!bad, "ulaw preserves the sign of a clearly non-zero sample");
	if (bad) printf("    counterexample: s=%d -> decode(encode(s))=%d\n", bs, bd);
}


/* ---- audio_to_model_pcm (the model-input representation) ------------------------------------ */

/* Output length is exactly floor(in_n/2) clamped to out_cap, and every output equals the mu-law
 * round-trip of the pairwise-averaged 16 kHz pair. Fuzzed over random windows and caps. */
static void test_audio_to_model_pcm_property(void)
{
	int bad = 0;
	for (int iter = 0; iter < 4000 && !bad; iter++) {
		size_t in_n = xr() % 200;
		size_t cap  = xr() % 120;
		int16_t in[200], out[120];
		for (size_t i = 0; i < in_n; i++) in[i] = rnd16();
		size_t got = audio_to_model_pcm(in, in_n, out, cap);
		size_t want = in_n / 2; if (want > cap) want = cap;
		if (got != want) { bad = 1; break; }
		for (size_t i = 0; i < got; i++) {
			int16_t avg = (int16_t)(((int32_t)in[2 * i] + in[2 * i + 1]) / 2);
			if (out[i] != ulaw_decode(ulaw_encode(avg))) { bad = 1; break; }
		}
	}
	CHECK(!bad, "audio_to_model_pcm: correct length and per-sample mu-law round-trip");
}

/* DIFFERENTIAL: the collar's TRAINING wire path (audio.c decimates 16->8 kHz by pairwise average then
 * mu-law-encodes; the station decodes back to PCM for the WAV) must yield the SAME samples as
 * audio_to_model_pcm, the INFERENCE representation the model sees. A train/inference representation
 * mismatch is the worst kind of accuracy bug, so this pins the two together. The decimation reproduced
 * here mirrors audio.c's , the shared spec both sides must follow. */
static void test_training_and_inference_representations_match(void)
{
	int bad = 0;
	for (int iter = 0; iter < 4000 && !bad; iter++) {
		size_t pairs = 1 + xr() % 100;
		size_t in_n  = pairs * 2;
		int16_t in[200], model[100];
		for (size_t i = 0; i < in_n; i++) in[i] = rnd16();
		size_t got = audio_to_model_pcm(in, in_n, model, pairs);
		for (size_t i = 0; i < got; i++) {
			int16_t avg = (int16_t)(((int32_t)in[2 * i] + in[2 * i + 1]) / 2);
			int16_t train_pcm = ulaw_decode(ulaw_encode(avg));   /* what the station stores from the wire */
			if (train_pcm != model[i]) { bad = 1; break; }
		}
	}
	CHECK(!bad, "training wire representation == inference model representation");
}


int main(void)
{
	test_ulaw_byte_roundtrip_consistent();
	test_ulaw_preserves_sign();
	test_audio_to_model_pcm_property();
	test_training_and_inference_representations_match();
	return test_report("audio_codec");
}
