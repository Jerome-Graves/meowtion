/*
 * Production-mode on-device classification , the always-on inference path.
 *
 * When a trained IMU model is present AND the collar is NOT in a training-capture stream, the
 * collar stops emitting SIMULATED telemetry and instead runs the action cascade (classifier.c) on
 * a rolling window of the most recent IMU samples, writing the real class + confidence into the
 * telemetry packet each cycle. This is "production mode": a trained model drives live detections.
 *
 * The simulated path (main.c) remains the pre-training fallback , production_active() decides which
 * branch runs each cycle, so the two never fight over the telemetry bytes.
 *
 * PRODUCTION TELEMETRY CONTRACT (manufacturer AD data, 8 bytes):
 *   [0..1] company id (0xFFFF)
 *   [2]    version = 2  (2 = real on-device classification; 1 = simulated, see main.c)
 *   [3]    class INDEX (0..N-1) into the trained model's label table; 0xFF = UNKNOWN/low-confidence;
 *          0xFE = low-power REST (rules-based gate; the station logs the span as a rest episode)
 *   [4]    confidence 0..100  (round(confidence * 100))
 *   [5..6] steps (uint16 LE) , keeps accruing from IMU motion as in the simulated path
 *   [7]    battery (0..100)
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

/* True when production mode should drive telemetry this cycle:
 * a trained IMU model is linked AND we are not in a capture/training stream. */
bool production_active(void);

/* Run one production-mode classification cycle and write the real-classification telemetry
 * packet (version=2) per the contract above. Maintains the rolling IMU window and the step count.
 * Call once per main-loop tick while production_active() is true. */
void production_update_telemetry(void);

/* Tell the production path it is not driving this cycle (e.g. a capture stream took over the IMU,
 * or no model is present). Releases our IMU ownership so a later re-entry restarts cleanly and
 * does not fight the capture path. Call when production_active() is false. */
void production_yield(void);

/* Peak accel-magnitude deviation from 1 g (milli-g) over the samples drained in the most recent
 * production_update_telemetry() cycle. A motion-energy proxy that feeds the rules-based activity
 * gate (activity.h); 0 when the last cycle drained no samples. */
uint32_t production_peak_mg(void);
