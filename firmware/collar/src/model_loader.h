/*
 * Runtime model-load API for the on-collar TFLite-Micro classifier.
 *
 * The collar ships with NO model compiled in (see tflm_classifier.cpp for the full design notes).
 * The two inference stages (IMU, audio) share ONE tensor arena and are never both resident: until a
 * model is installed clf_*_model_present() is false and the cascade in classifier.c runs model-free,
 * returning CLF_UNKNOWN. A model is installed at runtime , the intended path is a Phase-3 OTA push
 * that writes a .tflite flatbuffer into a buffer the caller keeps alive, then calls the matching
 * setter below.
 *
 * Each setter registers that stage's model and loads it into the shared arena once to validate it
 * (AllocateTensors). It returns true only if that succeeds; from then present() is true and the stage
 * infers, with the resident model flipping between stages on demand so only one is ever in RAM. On any
 * failure (null buffer, bad flatbuffer, arena too small) present() stays false and the firmware keeps
 * running model-free.
 *
 * OWNERSHIP: the model buffer is NOT copied. The caller guarantees it persists for as long as the
 * model is in use (e.g. it lives in a static/OTA-staging region, not on the stack).
 */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Install / replace the IMU-stage model. buf points to a .tflite flatbuffer of length len that the
 * caller keeps alive. Returns true on success (interpreter built + tensors allocated). */
bool clf_set_imu_model(const uint8_t *buf, size_t len);

/* Install / replace the audio-stage model. Same contract as clf_set_imu_model. */
bool clf_set_audio_model(const uint8_t *buf, size_t len);

#ifdef __cplusplus
}
#endif
