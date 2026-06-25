/*
 * The confidence-gated cascade. See classifier.h for the design.
 *
 * Right now it runs model-free: the two inference hooks below are weak stubs that report "no
 * prediction", and the *_present() flags are false. The cascade still executes correctly , it just
 * always yields CLF_UNKNOWN, so the rest of the firmware (simulated telemetry, audio capture for
 * data collection) is unaffected.
 *
 * To add a model later:
 *   1. Provide a STRONG definition of imu_model_infer() (and/or audio_model_infer()) in a new file,
 *      e.g. wrapping TFLite-Micro or a generated inference function.
 *   2. Provide a STRONG clf_imu_model_present() (and/or audio) returning true.
 * The weak stubs here are then overridden automatically. No caller changes.
 */
#include "classifier.h"

/* ---- model hooks (WEAK STUBS , no trained models yet) -------------------------------------- */

__attribute__((weak)) bool clf_imu_model_present(void)   { return false; }
__attribute__((weak)) bool clf_audio_model_present(void) { return false; }

__attribute__((weak)) clf_result_t imu_model_infer(const imu_features_t *feat)
{
	(void)feat;
	return (clf_result_t){ .cls = CLF_UNKNOWN, .confidence = 0.0f };
}

__attribute__((weak)) clf_result_t audio_model_infer(const int16_t *pcm, size_t pcm_len)
{
	(void)pcm; (void)pcm_len;
	return (clf_result_t){ .cls = CLF_UNKNOWN, .confidence = 0.0f };
}

/* ---- cascade -------------------------------------------------------------------------------- */

static clf_config_t g_cfg = {
	.audio_confirm_enabled = true,    /* on while we build trust in the IMU model; flip off to save power */
	.conf_threshold        = 0.75f,   /* below this stage-1 confidence, consult audio (when enabled + present) */
};

void clf_init(void) { /* reserved for model / feature-extractor setup */ }

clf_config_t *clf_get_config(void) { return &g_cfg; }

clf_result_t clf_classify(const imu_features_t *feat, const int16_t *pcm, size_t pcm_len)
{
	/* Stage 1: IMU , cheap, always runs. Model-free this is UNKNOWN / 0. */
	clf_result_t r = imu_model_infer(feat);

	/* Stage 2: audio confirm , only when enabled AND a model is present AND stage 1 was unsure.
	 * This is the gate: a confident IMU result skips audio entirely, and with no audio model we
	 * simply keep the IMU result. */
	if (g_cfg.audio_confirm_enabled && clf_audio_model_present() &&
	    r.confidence < g_cfg.conf_threshold && pcm && pcm_len > 0) {
		clf_result_t a = audio_model_infer(pcm, pcm_len);
		if (a.confidence > r.confidence) {
			r = a;   /* trust the more-confident stage */
		}
	}
	return r;
}
