/*
 * Battery sensing , 1S LiPo charge via the XIAO's onboard divider.
 *
 * The pack sits behind a 1M/510k divider on AIN7 (P0.31), gated by an enable GPIO (P0.14) so the
 * divider only draws current while we measure. This module owns the ADC + GPIO; main just reads a
 * percentage each telemetry cycle.
 */
#pragma once
#include <stdint.h>

/* Configure the battery ADC channel and the divider-enable GPIO (divider left off). */
void battery_init(void);

/* Sample the pack and return charge 0..100 (1S LiPo: 3.0 V = 0%, 4.2 V = 100%). Returns the last
 * known value on error. Rises while charging over USB (charging raises the pack voltage). */
uint8_t read_battery(void);
