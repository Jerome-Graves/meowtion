/*
 * Meowtion OTA model-delivery wire protocol , the contract between the collar and the station.
 *
 * SINGLE SOURCE OF TRUTH (same role as meow_protocol.h): both firmwares include this one header so
 * the OTA transfer format stays in sync. The collar (Zephyr / nRF Connect SDK) is the GATT server
 * that receives a trained .tflite model and stages it into flash; the station (ESP-IDF / NimBLE) is
 * the client that pushes it. This file defines ONLY wire-level things , opcodes, status codes, the
 * begin/header structs, and the three service UUIDs. Flash offsets and slot layout are a collar
 * implementation detail and live in collar/src/ota.c, NOT here.
 *
 * THE FLOW (one transfer at a time):
 *   1. client writes the CONTROL char: [MEOW_OTA_OP_BEGIN][meow_ota_begin]  , slot, total_len, crc32
 *      collar erases that slot and replies (CONTROL notify) MEOW_OTA_ST_READY (or an ERR_*).
 *   2. client writes the DATA char in chunks (write-with-response = natural flow control while flash
 *      erases/programs). collar streams them to flash and stays silent on the status channel during
 *      streaming , each chunk's write-response is the pacing, so the next status notify is END's.
 *   3. client writes CONTROL: [MEOW_OTA_OP_END]. collar flushes, re-reads the model from flash and
 *      verifies CRC-32/IEEE against `crc32`. On match it writes the slot header (LAST , see below)
 *      and hot-loads the model, then notifies MEOW_OTA_ST_OK. On any failure it notifies an ERR_*.
 *   MEOW_OTA_OP_ABORT (or a disconnect mid-transfer) discards the partial write. Because the slot
 *   header is committed LAST, a power-fail or abort leaves the slot header-less, so the collar's
 *   load-on-boot path simply ignores it , the previous model (if any) survives.
 *
 * CRC is CRC-32/IEEE (the same polynomial as zlib / zephyr crc32_ieee) over the model bytes only.
 */
#pragma once
#include <stdint.h>

/* Which model slot a transfer targets. The collar has one slot per inference stage. */
enum {
	MEOW_OTA_SLOT_IMU   = 0,   /* stage-1 IMU model */
	MEOW_OTA_SLOT_AUDIO = 1,   /* stage-2 audio-confirm model */
	MEOW_OTA_SLOT_COUNT = 2,
};

/* CONTROL-char write: the first byte is one of these opcodes. BEGIN is followed by a meow_ota_begin;
 * END and ABORT carry no payload. */
enum {
	MEOW_OTA_OP_BEGIN = 1,
	MEOW_OTA_OP_END   = 2,
	MEOW_OTA_OP_ABORT = 3,
};

/* Status the collar notifies back on the CONTROL char (one byte). */
enum {
	MEOW_OTA_ST_IDLE      = 0,   /* no transfer in progress */
	MEOW_OTA_ST_READY     = 1,   /* BEGIN accepted, slot erased , send DATA */
	MEOW_OTA_ST_RECEIVING = 2,   /* DATA chunks are being written */
	MEOW_OTA_ST_OK        = 3,   /* END: CRC verified, header committed, model loaded */
	MEOW_OTA_ST_ERR_SLOT  = 4,   /* slot index out of range */
	MEOW_OTA_ST_ERR_SIZE  = 5,   /* total_len exceeds the slot capacity (or DATA overran it) */
	MEOW_OTA_ST_ERR_FLASH = 6,   /* flash erase / write / area-open failed */
	MEOW_OTA_ST_ERR_CRC   = 7,   /* END: re-read CRC did not match the announced crc32 */
	MEOW_OTA_ST_ERR_SEQ   = 8,   /* protocol misuse (DATA with no BEGIN, overrun, ...) */
	MEOW_OTA_ST_ERR_LOAD  = 9,   /* model verified but the classifier rejected it (arena too small) */
};

/* CONTROL payload that FOLLOWS the MEOW_OTA_OP_BEGIN byte. `total_len` is the model byte count;
 * `crc32` is CRC-32/IEEE over those bytes. _rsvd keeps the 32-bit fields naturally aligned. */
struct __attribute__((packed)) meow_ota_begin {
	uint8_t  slot;        /* MEOW_OTA_SLOT_* */
	uint8_t  _rsvd;
	uint32_t total_len;   /* model size in bytes */
	uint32_t crc32;       /* CRC-32/IEEE over the model bytes */
};

/* The collar writes this to a slot's header page on a verified commit, and validates it on boot.
 * magic present + crc matching the stored bytes == "this slot holds a valid model of `len` bytes".
 * Written LAST so a partial/aborted transfer never looks valid. */
#define MEOW_OTA_SLOT_MAGIC 0x4D544F4Du   /* 'M''O''T''M' little-endian , MeowtionOTAModel */
struct __attribute__((packed)) meow_ota_slot_hdr {
	uint32_t magic;       /* MEOW_OTA_SLOT_MAGIC */
	uint32_t len;         /* model byte count */
	uint32_t crc32;       /* CRC-32/IEEE over the model bytes */
	uint32_t _rsvd;
};

/*
 * The three 128-bit GATT UUIDs for the OTA service. They share the Meowtion base used by the audio
 * service (ble.c) but use the 0x0b** group so they are distinct:
 *
 *   service  : 4d656f77-0b01-4175-6469-6f0053657600
 *   control  : 4d656f77-0b02-4175-6469-6f0043747200
 *   data     : 4d656f77-0b03-4175-6469-6f0044617400
 *
 * Two ways to construct them, kept consistent so both builds agree on the bytes:
 *   - Zephyr (collar): pass the documented groups to BT_UUID_128_ENCODE (see ota.c). That macro
 *     emits the 16 bytes in little-endian order , exactly the *_BYTES arrays below.
 *   - ESP-IDF / NimBLE (station): use the raw little-endian 16-byte arrays directly
 *     (e.g. ble_uuid128_t / esp_bt_uuid_t store the 128-bit value little-endian).
 *
 * A canonical UUID aabbccdd-eeff-gghh-iijj-kkllmmnnoopp becomes the little-endian array
 * { pp,oo,nn,mm,ll,kk, jj,ii, hh,gg, ff,ee, dd,cc,bb,aa } , i.e. the textual byte order reversed.
 */
#define MEOW_OTA_SVC_UUID_BYTES { \
	0x00, 0x76, 0x65, 0x53, 0x00, 0x6f, 0x69, 0x64, \
	0x75, 0x41, 0x01, 0x0b, 0x77, 0x6f, 0x65, 0x4d }

#define MEOW_OTA_CTRL_UUID_BYTES { \
	0x00, 0x72, 0x74, 0x43, 0x00, 0x6f, 0x69, 0x64, \
	0x75, 0x41, 0x02, 0x0b, 0x77, 0x6f, 0x65, 0x4d }

#define MEOW_OTA_DATA_UUID_BYTES { \
	0x00, 0x74, 0x61, 0x44, 0x00, 0x6f, 0x69, 0x64, \
	0x75, 0x41, 0x03, 0x0b, 0x77, 0x6f, 0x65, 0x4d }
