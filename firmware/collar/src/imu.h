/*
 * Onboard IMU (LSM6DS3TR-C) , continuous sampler.
 *
 * While streaming is active the IMU is sampled at IMU_RATE_HZ into a ring buffer; the audio stream
 * thread drains it once per 100 ms audio frame so each frame carries the motion captured alongside
 * it. Units: accel = milli-g, gyro = centi-deg/s. Each sample is 6 interleaved int16
 * [ax, ay, az, gx, gy, gz]. 104 Hz gives a 52 Hz ceiling , enough for the ~25 Hz purr vibration and
 * the slow head-motion of eating / drinking.
 */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define IMU_RATE_HZ  104
#define IMU_AXES     6

bool imu_init(void);

void imu_stream_start(void);   /* begin continuous sampling into the ring */
void imu_stream_stop(void);    /* stop sampling */

/* Copy up to max_vals int16 out of the ring into dst (kept a multiple of IMU_AXES so whole samples
 * are never split). Returns the number of int16 copied. */
size_t imu_drain(int16_t *dst, size_t max_vals);

/* Low-power rest support (rules-based activity gate, see activity.h).
 * imu_set_lowpower(true) drops the IMU to a low-power watch ODR (~12.5 Hz); false restores the
 * IMU_RATE_HZ sampling rate used for classification. Call with the stream stopped. */
void imu_set_lowpower(bool low);

/* One-shot accelerometer read for the motion watch while the 104 Hz stream is stopped. Returns the
 * magnitude of (acceleration - 1 g) in milli-g, a motion-energy proxy; 0 on a read error or before
 * imu_init(). */
uint32_t imu_motion_mg(void);
