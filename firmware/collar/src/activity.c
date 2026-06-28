/* Rules-based activity gate (cascade tier 0). See activity.h. Pure still-timer policy. */
#include "activity.h"

/* Accumulated seconds the cat has been continuously "still". Reset by motion or activity_reset(). */
static uint32_t g_still_s;

void activity_reset(void) { g_still_s = 0; }

bool activity_should_rest(uint32_t peak_mg, uint32_t dt_s)
{
	if (peak_mg >= ACT_STILL_MG) {   /* any real motion restarts the hold-off */
		g_still_s = 0;
		return false;
	}
	g_still_s += dt_s;
	return g_still_s >= ACT_REST_HOLDOFF_S;
}
