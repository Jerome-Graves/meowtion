/* Host unit tests for the rules-based activity gate (collar/src/activity.c, cascade tier 0).
 * Pure logic, no Zephyr. Built and run on the host. See firmware/test/Makefile.
 *
 *   make -C firmware/test check
 */
#include "activity.h"
#include "test_util.h"

/* Motion at or above the still threshold must never let the gate drop to rest. */
static void test_motion_keeps_awake(void)
{
	activity_reset();
	for (int i = 0; i < 100; i++) {
		CHECK(!activity_should_rest(ACT_STILL_MG + 50, 2), "motion should not rest");
	}
}

/* Sustained stillness past the hold-off trips rest, but not before. */
static void test_sustained_stillness_trips_rest(void)
{
	activity_reset();
	for (uint32_t t = 0; t < ACT_REST_HOLDOFF_S - 2; t += 2) {
		CHECK(!activity_should_rest(0, 2), "should not rest before the hold-off");
	}
	CHECK(activity_should_rest(0, 2), "should rest once still past the hold-off");
}

/* Any motion resets the still-timer, so rest needs another full hold-off afterwards. */
static void test_motion_resets_the_timer(void)
{
	activity_reset();
	for (uint32_t t = 0; t < ACT_REST_HOLDOFF_S - 2; t += 2) {
		(void)activity_should_rest(0, 2);
	}
	CHECK(!activity_should_rest(ACT_STILL_MG, 2), "motion at/over threshold resets the timer");
	CHECK(!activity_should_rest(0, 2), "must not rest immediately after a reset");
}

int main(void)
{
	test_motion_keeps_awake();
	test_sustained_stillness_trips_rest();
	test_motion_resets_the_timer();
	return test_report("activity");
}
