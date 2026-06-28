/* LSM6DS3TR-C continuous sampler , see imu.h. Polled at a fixed rate into an SPSC ring. */
#include "imu.h"

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/drivers/regulator.h>
#include <zephyr/logging/log.h>
#include <math.h>

LOG_MODULE_REGISTER(imu, LOG_LEVEL_INF);

/* The board DTS (xiao_ble ...sense) declares this node: lsm6ds3tr_c@6a, compatible st,lsm6dsl. */
static const struct device *imu_dev = DEVICE_DT_GET(DT_NODELABEL(lsm6ds3tr_c));
/* The load switch that powers the IMU rail (board node /lsm6ds3tr-c-en). */
static const struct device *imu_pwr = DEVICE_DT_GET(DT_PATH(lsm6ds3tr_c_en));
static bool g_ready;

/* SPSC ring of int16. Producer = imu_thread (head), consumer = imu_drain (tail). Power-of-two so the
 * index wraps with a mask. ~3 s of headroom at 104 Hz * 6 axes. */
#define RING_CAP 2048
static int16_t ring[RING_CAP];
static volatile uint32_t r_head, r_tail;
static volatile bool g_run;

#define G_TO_MS2    9.80665
#define RAD_TO_DEG  57.2957795

static int16_t clamp16(double v)
{
	if (v > 32767.0)  return 32767;
	if (v < -32768.0) return -32768;
	return (int16_t)v;
}

bool imu_init(void)
{
	/* Power the IMU rail explicitly, then give the chip its boot time before we touch it. The
	 * sensor node is marked zephyr,deferred-init so its driver init runs HERE (called from main,
	 * well after boot) instead of in the tight POST_KERNEL window , that earlier window ran before
	 * the rail had settled, so the driver's first I2C read NACKed and init failed ("Failed to
	 * initialize chip"). Enabling the regulator here also covers the case where boot-on didn't. */
	if (device_is_ready(imu_pwr)) {
		int re = regulator_enable(imu_pwr);
		if (re) LOG_WRN("IMU regulator enable rc=%d", re);
	} else {
		LOG_WRN("IMU regulator device not ready");
	}
	k_msleep(30);   /* LSM6DS3TR-C datasheet boot time ~15 ms; double it for margin */

	int ic = device_init(imu_dev);
	if (ic && ic != -EALREADY) {
		LOG_ERR("LSM6DS3TR-C init failed (rc=%d)", ic);
		return false;
	}
	if (!device_is_ready(imu_dev)) {
		LOG_ERR("LSM6DS3TR-C not ready after init");
		return false;
	}
	struct sensor_value odr = { .val1 = IMU_RATE_HZ, .val2 = 0 };
	int e1 = sensor_attr_set(imu_dev, SENSOR_CHAN_ACCEL_XYZ, SENSOR_ATTR_SAMPLING_FREQUENCY, &odr);
	int e2 = sensor_attr_set(imu_dev, SENSOR_CHAN_GYRO_XYZ,  SENSOR_ATTR_SAMPLING_FREQUENCY, &odr);
	if (e1 || e2) LOG_WRN("ODR set rc=%d/%d (using driver default)", e1, e2);

	g_ready = true;
	LOG_INF("IMU ready (%d Hz, accel mg + gyro cdps)", IMU_RATE_HZ);
	return true;
}

void imu_stream_start(void)
{
	r_head = r_tail = 0;   /* safe: the consumer (drain) isn't running between clips */
	g_run = true;
}

void imu_stream_stop(void) { g_run = false; }

/* push one 6-axis sample (all or nothing, so the ring stays IMU_AXES-aligned) */
static void push_sample(const int16_t *s)
{
	if ((r_head - r_tail) > (RING_CAP - IMU_AXES)) return;   /* full: drop this sample */
	for (int i = 0; i < IMU_AXES; i++) ring[(r_head + i) & (RING_CAP - 1)] = s[i];
	r_head += IMU_AXES;
}

size_t imu_drain(int16_t *dst, size_t max_vals)
{
	uint32_t avail = r_head - r_tail;              /* head only grows; snapshot is fine */
	size_t n = (avail < max_vals) ? avail : max_vals;
	n -= (n % IMU_AXES);                            /* whole samples only */
	for (size_t i = 0; i < n; i++) dst[i] = ring[(r_tail + i) & (RING_CAP - 1)];
	r_tail += n;
	return n;
}

void imu_set_lowpower(bool low)
{
	if (!g_ready) return;
	/* Lower both ODRs for the rest watch (accel + gyro), restore IMU_RATE_HZ for classification.
	 * 12 maps to the LSM6DS3TR-C's 12.5 Hz step; the driver rounds to the nearest supported rate. */
	int hz = low ? 12 : IMU_RATE_HZ;
	struct sensor_value odr = { .val1 = hz, .val2 = 0 };
	(void)sensor_attr_set(imu_dev, SENSOR_CHAN_ACCEL_XYZ, SENSOR_ATTR_SAMPLING_FREQUENCY, &odr);
	(void)sensor_attr_set(imu_dev, SENSOR_CHAN_GYRO_XYZ,  SENSOR_ATTR_SAMPLING_FREQUENCY, &odr);
}

uint32_t imu_motion_mg(void)
{
	if (!g_ready) return 0;
	struct sensor_value acc[3];
	if (sensor_sample_fetch(imu_dev) != 0) return 0;
	if (sensor_channel_get(imu_dev, SENSOR_CHAN_ACCEL_XYZ, acc) != 0) return 0;
	double mg[3];
	for (int i = 0; i < 3; i++)
		mg[i] = sensor_value_to_double(&acc[i]) * 1000.0 / G_TO_MS2;   /* milli-g */
	double mag = sqrt(mg[0] * mg[0] + mg[1] * mg[1] + mg[2] * mg[2]);
	double dev = mag - 1000.0;                                         /* deviation from 1 g */
	if (dev < 0.0) dev = -dev;
	return (uint32_t)dev;
}

static void imu_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a); ARG_UNUSED(b); ARG_UNUSED(c);
	const int64_t period_us = 1000000 / IMU_RATE_HZ;   /* ~9615 us @ 104 Hz */
	struct sensor_value acc[3], gyr[3];
	int16_t s[IMU_AXES];

	while (1) {
		if (!g_ready || !g_run) { k_sleep(K_MSEC(50)); continue; }
		int64_t t0 = k_uptime_ticks();

		if (sensor_sample_fetch(imu_dev) == 0 &&
		    sensor_channel_get(imu_dev, SENSOR_CHAN_ACCEL_XYZ, acc) == 0 &&
		    sensor_channel_get(imu_dev, SENSOR_CHAN_GYRO_XYZ,  gyr) == 0) {
			for (int i = 0; i < 3; i++)
				s[i]     = clamp16(sensor_value_to_double(&acc[i]) * 1000.0 / G_TO_MS2);   /* mg */
			for (int i = 0; i < 3; i++)
				s[3 + i] = clamp16(sensor_value_to_double(&gyr[i]) * RAD_TO_DEG * 100.0);  /* cdps */
			push_sample(s);
		}

		int64_t spent_us = k_ticks_to_us_floor64(k_uptime_ticks() - t0);
		if (spent_us < period_us) k_usleep((int32_t)(period_us - spent_us));
	}
}
K_THREAD_DEFINE(imu_tid, 3072, imu_thread, NULL, NULL, NULL, 7, 0, 0);
