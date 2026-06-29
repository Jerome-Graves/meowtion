# Host unit tests for the pure collar logic (no Zephyr, no hardware). Needs only a host C
# compiler. Run:  make -C firmware/test check
CC     ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -O0 -I../collar/src
SRC     = ../collar/src
BINS    = test_activity test_classifier

check: $(BINS)
	./test_activity
	./test_classifier

test_activity: test_activity.c $(SRC)/activity.c test_util.h
	$(CC) $(CFLAGS) test_activity.c $(SRC)/activity.c -o $@

test_classifier: test_classifier.c $(SRC)/classifier.c test_util.h
	$(CC) $(CFLAGS) test_classifier.c $(SRC)/classifier.c -o $@

clean:
	rm -f $(BINS) test_activity.exe test_classifier.exe

.PHONY: check clean
