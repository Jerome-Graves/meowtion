# Host unit tests for the pure collar logic (no Zephyr, no hardware). Needs only a host C
# compiler. Run:  make -C firmware/test check
CC     ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -O0 -I../collar/src
SRC     = ../collar/src
BINS    = test_activity test_classifier test_audio_codec

check: $(BINS)
	./test_activity
	./test_classifier
	./test_audio_codec

test_activity: test_activity.c $(SRC)/activity.c test_util.h
	$(CC) $(CFLAGS) test_activity.c $(SRC)/activity.c -o $@

test_classifier: test_classifier.c $(SRC)/classifier.c test_util.h
	$(CC) $(CFLAGS) test_classifier.c $(SRC)/classifier.c -o $@

# The audio codec + representation are header-only (mu-law in firmware/common, the model transform in
# collar/src); the test needs both include dirs and no .c beyond itself.
test_audio_codec: test_audio_codec.c $(SRC)/audio_codec.h ../common/meow_protocol.h test_util.h
	$(CC) $(CFLAGS) -I../common test_audio_codec.c -o $@

clean:
	rm -f $(BINS) test_activity.exe test_classifier.exe test_audio_codec.exe

.PHONY: check clean
