/* Tiny zero-dependency unit-test helper for the host-compiled collar logic tests.
 * CHECK records a pass/fail; test_report() prints a summary and returns nonzero if anything failed
 * (so `make check` / CI fails the build). No framework needed; just a host C compiler. */
#pragma once
#include <stdio.h>

static int _checks = 0;
static int _fails = 0;

#define CHECK(cond, msg)                                                        \
	do {                                                                         \
		_checks++;                                                               \
		if (!(cond)) {                                                           \
			_fails++;                                                            \
			printf("  FAIL: %s (%s:%d)\n", (msg), __FILE__, __LINE__);          \
		}                                                                        \
	} while (0)

static int test_report(const char *suite)
{
	printf("[%s] %d checks, %d failed\n", suite, _checks, _fails);
	return _fails ? 1 : 0;
}
