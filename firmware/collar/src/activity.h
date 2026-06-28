/*
 * Rules-based activity gate , cascade TIER 0 (runs before the model-based tiers).
 *
 * The model tiers (IMU CNN, then audio CNN) are only worth running while the cat is actually doing
 * something. Most of a cat's day is rest/sleep, and classifying stillness 50 times a second drains
 * the cell for no information. This tier is a cheap motion-energy rule that decides "active vs
 * resting" with no model at all:
 *
 *   active  -> hand off to the model cascade (production.c / classifier.c) as usual.
 *   resting -> sustained low motion past a hold-off drops the collar into low-power rest (main.c):
 *              the 104 Hz stream and inference stop, the IMU drops to a low-power watch ODR, and the
 *              radio slows. A motion event ends rest, and the station logs the whole dormant span as
 *              a single rest episode (the "rest event").
 *
 * This module is pure policy (a still-timer over a motion-energy proxy). main.c owns the hardware
 * power transitions and the low-power motion watch; production.c feeds the per-cycle motion proxy.
 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Peak accel-magnitude deviation from 1 g (milli-g) at or below which a cycle counts as "still".
 * A resting cat sits near 1 g (deviation ~0); small grooming/shuffles stay under this. */
#define ACT_STILL_MG        150u
/* Sustained-still time (seconds) before the gate drops the collar to low-power rest. */
#define ACT_REST_HOLDOFF_S   60u
/* Motion (mg deviation) during the rest watch that ends rest and re-arms the model cascade. */
#define ACT_WAKE_MG         220u

/* Forget any accumulated stillness (call on waking, or when entering production). */
void activity_reset(void);

/* Feed one active cycle: peak motion this cycle (mg deviation from 1 g) and the seconds elapsed
 * since the previous call. Returns true once stillness has persisted past ACT_REST_HOLDOFF_S, i.e.
 * the collar should enter low-power rest. */
bool activity_should_rest(uint32_t peak_mg, uint32_t dt_s);
