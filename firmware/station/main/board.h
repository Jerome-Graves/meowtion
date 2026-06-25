#pragma once
/* board.h , board power sensing (USB vs battery on A0). */

/* Latest power source: "usb" or "battery". */
extern const char *g_power;
/* Battery charge percent (0..100), or -1 when on USB / no battery. */
extern int g_batt_pct;

void power_init(void);   /* configure the A0 ADC + pulldown; call once at boot */
void read_power(void);   /* sample A0 and update g_power / g_batt_pct */
