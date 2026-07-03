/*
 * board.c , board power sensing.
 *
 * Sole job: tell the rest of the firmware whether the station is running on USB or a battery,
 * and (when on battery) the rough charge percent. Everything else about the hardware lives in
 * its own module.
 */
#include "board.h"

#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"

/* ---------------- power source (battery wired to A0, or USB) ----------------
 * A 2x220 ohm divider on A0 (GPIO1 / ADC1_CH0) reads Vbat/2 when a battery is wired in.
 * With the internal pulldown enabled, an unwired (USB-only) pin floats low instead. So a
 * real voltage => battery present (and a %); near-zero => USB powered.
 * NOTE: the 500 mV threshold and pulldown behaviour should be confirmed on the real board. */
static adc_oneshot_unit_handle_t s_adc = NULL;

const char *g_power = "usb";
int g_batt_pct = -1;            /* -1 when USB / no battery */

/* A0 reads VBAT through a 2x220k divider. 1S LiPo percent is a crude LINEAR map (not a real
 * state-of-charge curve): 3.0 V = 0%, 4.2 V = 100%. */
#define BATT_MV_EMPTY     3000
#define BATT_MV_FULL      4200
#define BATT_ADC_SAMPLES  8

void power_init(void)
{
    gpio_set_pull_mode(GPIO_NUM_1, GPIO_PULLDOWN_ONLY);   /* A0 floats low when no battery divider */
    adc_oneshot_unit_init_cfg_t u = { .unit_id = ADC_UNIT_1 };
    if (adc_oneshot_new_unit(&u, &s_adc) != ESP_OK) { s_adc = NULL; return; }
    adc_oneshot_chan_cfg_t c = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT };
    adc_oneshot_config_channel(s_adc, ADC_CHANNEL_0, &c);   /* ADC1_CH0 = GPIO1 = A0 */
}

void read_power(void)
{
    if (!s_adc) { g_power = "usb"; g_batt_pct = -1; return; }
    int sum = 0, raw = 0, ok = 0;
    for (int i = 0; i < BATT_ADC_SAMPLES; i++)
        if (adc_oneshot_read(s_adc, ADC_CHANNEL_0, &raw) == ESP_OK) { sum += raw; ok++; }
    if (ok == 0) { g_power = "usb"; g_batt_pct = -1; return; }    /* every read failed */
    int mv = (sum / ok) * 3300 / 4095;           /* average only successful reads; ~0-3.3 V at 12 dB atten */
    if (mv < 500) { g_power = "usb"; g_batt_pct = -1; return; }   /* floats low => no battery wired */
    int vbat = mv * 2;                            /* undo the 2x220 divider */
    int pct = (vbat - BATT_MV_EMPTY) * 100 / (BATT_MV_FULL - BATT_MV_EMPTY);   /* percent (linear) */
    g_power = "battery";
    g_batt_pct = pct < 0 ? 0 : (pct > 100 ? 100 : pct);
}
