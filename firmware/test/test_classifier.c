/* Host unit tests for the confidence-gated cascade policy (collar/src/classifier.c).
 *
 * classifier.c declares the model hooks WEAK, so we link strong definitions here and drive them
 * from globals to script each scenario, then assert the gating: the audio stage runs only when it
 * is enabled, a model is present, audio for the cycle exists, AND the IMU stage was not confident.
 *
 *   make -C firmware/test check
 */
#include <stddef.h>
#include <stdint.h>

#include "classifier.h"
#include "test_util.h"

/* test-controlled hook behaviour */
static clf_result_t g_imu;
static clf_result_t g_audio;
static bool         g_audio_present;
static int          g_audio_calls;

/* strong overrides of classifier.c's weak hooks */
bool clf_imu_model_present(void)   { return true; }
bool clf_audio_model_present(void) { return g_audio_present; }

clf_result_t imu_model_infer(const imu_features_t *feat)
{
	(void)feat;
	return g_imu;
}

clf_result_t audio_model_infer(const int16_t *pcm, size_t pcm_len)
{
	(void)pcm;
	(void)pcm_len;
	g_audio_calls++;
	return g_audio;
}

static const int16_t PCM[8] = {0};   /* a non-NULL audio buffer for "audio present this cycle" */

static void scenario(clf_result_t imu, clf_result_t audio, bool present)
{
	g_imu = imu;
	g_audio = audio;
	g_audio_present = present;
	g_audio_calls = 0;
	clf_get_config()->audio_confirm_enabled = true;
	clf_get_config()->conf_threshold = 0.75f;
}

static void test_confident_imu_skips_audio(void)
{
	scenario((clf_result_t){2, 0.90f}, (clf_result_t){5, 0.99f}, true);
	clf_result_t r = clf_classify(NULL, PCM, 8);
	CHECK(g_audio_calls == 0, "audio must not run when the IMU is confident");
	CHECK(r.cls == 2, "the confident IMU result is reported");
}

static void test_unsure_imu_consults_audio(void)
{
	scenario((clf_result_t){2, 0.40f}, (clf_result_t){5, 0.95f}, true);
	clf_result_t r = clf_classify(NULL, PCM, 8);
	CHECK(g_audio_calls == 1, "audio runs when the IMU is unsure");
	CHECK(r.cls == 5, "the more-confident audio result wins");
}

static void test_audio_kept_only_when_more_confident(void)
{
	scenario((clf_result_t){2, 0.40f}, (clf_result_t){5, 0.30f}, true);
	clf_result_t r = clf_classify(NULL, PCM, 8);
	CHECK(g_audio_calls == 1, "audio still runs (IMU unsure)");
	CHECK(r.cls == 2, "keep the IMU result when audio is less confident");
}

static void test_disabled_confirm_never_runs_audio(void)
{
	scenario((clf_result_t){2, 0.40f}, (clf_result_t){5, 0.95f}, true);
	clf_get_config()->audio_confirm_enabled = false;
	clf_result_t r = clf_classify(NULL, PCM, 8);
	CHECK(g_audio_calls == 0, "disabled audio-confirm never runs the audio stage");
	CHECK(r.cls == 2, "IMU result stands with confirm disabled");
}

static void test_no_pcm_skips_audio(void)
{
	scenario((clf_result_t){2, 0.40f}, (clf_result_t){5, 0.95f}, true);
	clf_result_t r = clf_classify(NULL, NULL, 0);   /* no audio this cycle (production IMU-only path) */
	CHECK(g_audio_calls == 0, "no audio this cycle -> audio stage skipped");
	CHECK(r.cls == 2, "IMU result stands when there is no audio");
}

static void test_no_audio_model_skips_audio(void)
{
	scenario((clf_result_t){2, 0.40f}, (clf_result_t){5, 0.95f}, false);
	clf_result_t r = clf_classify(NULL, PCM, 8);
	CHECK(g_audio_calls == 0, "no audio model present -> audio stage skipped");
	CHECK(r.cls == 2, "IMU result stands with no audio model");
}

int main(void)
{
	test_confident_imu_skips_audio();
	test_unsure_imu_consults_audio();
	test_audio_kept_only_when_more_confident();
	test_disabled_confirm_never_runs_audio();
	test_no_pcm_skips_audio();
	test_no_audio_model_skips_audio();
	return test_report("classifier");
}
