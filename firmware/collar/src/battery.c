/*
 * Battery sensing , 1S LiPo charge via the XIAO's onboard divider. See battery.h.
 *
 * AIN7 (P0.31) reads the pack through a 1M/510k divider; P0.14 gates it (active-low) so the divider
 * only bleeds current during a measurement (see app.overlay).
 */
#include "battery.h"

#include <zephyr/kernel.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(battery, LOG_LEVEL_INF);

static const struct adc_dt_spec  vbat_adc = ADC_DT_SPEC_GET_BY_IDX(DT_PATH(zephyr_user), 0);
static const struct gpio_dt_spec vbat_en  = GPIO_DT_SPEC_GET(DT_PATH(zephyr_user), vbat_en_gpios);

/* Last good reading, returned on a sensor error. Seeds the telemetry default before the first read. */
static uint8_t last_pct = 96;

void battery_init(void)
{
    if (gpio_is_ready_dt(&vbat_en)) gpio_pin_configure_dt(&vbat_en, GPIO_OUTPUT_INACTIVE);  /* divider off */
    if (adc_is_ready_dt(&vbat_adc)) adc_channel_setup_dt(&vbat_adc);
}

uint8_t read_battery(void)
{
    if (!adc_is_ready_dt(&vbat_adc)) return last_pct;

    gpio_pin_set_dt(&vbat_en, 1);          /* assert (active-low) => P0.14 low => divider on */
    k_sleep(K_MSEC(10));

    int16_t raw = 0;
    struct adc_sequence seq = { .buffer = &raw, .buffer_size = sizeof(raw), .calibrate = true };
    int err = adc_sequence_init_dt(&vbat_adc, &seq);
    if (!err) err = adc_read_dt(&vbat_adc, &seq);

    gpio_pin_set_dt(&vbat_en, 0);          /* divider off again (saves the ~3 uA bleed) */
    if (err) { LOG_WRN("battery adc err %d", err); return last_pct; }

    int32_t mv = raw;
    adc_raw_to_millivolts_dt(&vbat_adc, &mv);   /* mV at the ADC pin */
    int vbat = mv * (1000 + 510) / 510;         /* undo the 1M/510k divider */
    int pct = (vbat - 3000) * 100 / 1200;
    last_pct = pct < 0 ? 0 : (pct > 100 ? 100 : pct);
    return last_pct;
}
