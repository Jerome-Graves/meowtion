/*
 * On-collar action classifier , the confidence-gated cascade.
 *
 * Stage 1 is the IMU model (cheap, always runs). Stage 2 is an optional audio confirm model that
 * only runs when (a) it's enabled, (b) a model is actually linked, and (c) the IMU stage was not
 * confident. So when the IMU is sure the audio stage never fires (it "disables itself"), and when
 * battery matters you can switch it off entirely with one config flag.
 *
 * IMPORTANT: there are no trained models yet. The inference hooks are weak stubs that return "no
 * prediction", so this whole pipeline compiles and runs model-free. Dropping a model in later means
 * providing a strong definition of the hook + flipping its *_present() to true , nothing else
 * changes. See classifier.c.
 */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* The cascade is action-agnostic: it reports a CLASS INDEX, not a fixed enum, so the same firmware
 * recognises whatever actions the model was trained on (eat / drink / purr / scratch / litter / ...).
 * `cls` indexes the active model's label table , the names live in the generated model metadata
 * (e.g. imu_labels[] / audio_labels[] from software/training), not hardcoded here. */
#define CLF_UNKNOWN (-1)   /* no confident prediction */

typedef struct {
	int   cls;          /* class index into the model's label table, or CLF_UNKNOWN */
	float confidence;   /* 0..1 */
} clf_result_t;

/* The raw IMU window handed to the stage-1 model. Interleaved int16 frames [ax,ay,az,gx,gy,gz];
 * accel in milli-g, gyro in centi-deg/s. The model's own front-end extracts features from this, so
 * we pass the raw window rather than a fixed feature vector. samples==NULL/count==0 means "no IMU
 * this cycle" (the stub model just returns UNKNOWN). */
typedef struct {
	const int16_t *samples;   /* count int16 values = frames * 6 */
	size_t         count;
	uint16_t       rate_hz;
	uint8_t        axes;      /* 6 (accel x/y/z + gyro x/y/z) */
} imu_features_t;

/* Runtime config for the cascade. Defaults are safe with no models present. These two are what a
 * future BLE config characteristic will set from the dashboard. */
typedef struct {
	bool  audio_confirm_enabled;   /* allow stage-2 audio confirm at all */
	float conf_threshold;          /* below this stage-1 confidence, consult audio (if enabled+present) */
} clf_config_t;

void          clf_init(void);
clf_config_t *clf_get_config(void);

/* Is a trained model actually linked for that stage? Both false until we drop models in. */
bool clf_imu_model_present(void);
bool clf_audio_model_present(void);

/* The confidence-gated cascade. Model-free this returns CLF_UNKNOWN / 0. `pcm`/`pcm_len` may be
 * NULL/0 when there's no audio for this cycle , the audio stage is skipped in that case anyway.
 *
 * AUDIO CONTRACT: `pcm` MUST be in the model's training representation , 8 kHz, µ-law-companded
 * 16-bit (MODEL_AUDIO_RATE_HZ). Always produce it by running live mic audio through
 * audio_to_model_pcm() in audio_codec.h; that is the exact transform training clips went through.
 * Do NOT pass raw 16 kHz or clean PCM here , a train/inference mismatch wrecks accuracy. */
clf_result_t clf_classify(const imu_features_t *feat, const int16_t *pcm, size_t pcm_len);
