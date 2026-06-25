/*
 * Collar-side OTA model delivery (Phase 3).
 *
 * WHAT THIS DOES
 *   Receives a trained .tflite model over BLE from the station, stages it into a dedicated flash
 *   partition (models_storage, see pm_static.yml), and hands it straight to the TFLite-Micro engine
 *   (model_loader.h). The model then runs IN PLACE from flash , the nRF52840's internal flash is
 *   memory-mapped (XIP) at absolute address == flash offset, so clf_set_*_model() gets a pointer
 *   into flash and never copies the model into RAM (RAM is already ~78% full). Survives reboot:
 *   on boot we re-scan the slots and re-load any valid model, with no station required.
 *
 * FLASH LAYOUT (collar-internal , the wire protocol in common/meow_ota.h knows nothing of this).
 *   models_storage is 256 KB, split into two slots, one per inference stage. Each slot is laid out
 *   [page 0 = header (4 KB reserved)][model bytes from +0x1000]. So model capacity = slot - 0x1000.
 *     slot 0 (IMU)   : offset 0x00000, size 0x10000 (64 KB)  -> capacity 60 KB
 *     slot 1 (AUDIO) : offset 0x10000, size 0x30000 (192 KB) -> capacity 188 KB
 *   The header page holds a meow_ota_slot_hdr {magic,len,crc}. It is written LAST, after the model
 *   bytes are verified , so a crash or abort mid-transfer leaves the slot header-less and therefore
 *   "invalid", and the previous model (if any) survives. Power-fail safe by construction.
 *
 * TRANSFER FLOW (BEGIN / DATA / END , see common/meow_ota.h for the wire details).
 *   BEGIN  parse meow_ota_begin, range-check slot + size, ERASE the whole slot (header + model
 *          pages) up front, init a stream_flash writer into the model region. -> notify READY.
 *   DATA   stream the chunk to flash; bump `received`; reject an overrun. -> notify RECEIVING.
 *   END    flush, recompute CRC-32/IEEE over the written bytes by reading them back from the XIP
 *          address, compare to the announced crc. On match: write the slot header, then hot-load
 *          the model via clf_set_*_model(). -> notify OK (or ERR_CRC / ERR_LOAD).
 *   ABORT / disconnect mid-transfer just drops the state machine; the slot stays invalid.
 *
 * One transfer at a time, guarded by `xfer.active`. A fresh BEGIN while one is active resets it
 * (re-erases the slot and starts over) rather than rejecting , the simplest robust recovery.
 */
#include "ota.h"
#include "model_loader.h"

#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/storage/flash_map.h>
#include <zephyr/storage/stream_flash.h>
#include <zephyr/sys/crc.h>
#include <zephyr/sys/util.h>
#include <zephyr/logging/log.h>
#include <string.h>

#include "meow_ota.h"   /* shared wire protocol (../common is on the include path) */

LOG_MODULE_REGISTER(ota, LOG_LEVEL_INF);

/* ------------------------------- collar-internal slot map ------------------------------- */
/* Offsets/sizes WITHIN the models_storage partition. Kept here, not in the shared header. */
#define OTA_SLOT_HDR_SIZE   0x1000u   /* page 0 of each slot is the header (4 KB reserved) */

struct slot_def {
	uint32_t offset;   /* from the start of models_storage */
	uint32_t size;     /* total slot size (header page + model region) */
};
/* Order matches MEOW_OTA_SLOT_IMU(0) / MEOW_OTA_SLOT_AUDIO(1). */
static const struct slot_def slots[MEOW_OTA_SLOT_COUNT] = {
	[MEOW_OTA_SLOT_IMU]   = { .offset = 0x00000u, .size = 0x10000u },   /* 64 KB  */
	[MEOW_OTA_SLOT_AUDIO] = { .offset = 0x10000u, .size = 0x30000u },   /* 192 KB */
};

/* Usable model capacity of a slot (everything past its header page). */
static inline uint32_t slot_capacity(const struct slot_def *s)
{
	return s->size - OTA_SLOT_HDR_SIZE;
}
/* Absolute flash offset of a slot's model region (== XIP address on this SoC). */
static inline uint32_t slot_model_offset(const struct slot_def *s)
{
	return (uint32_t)FIXED_PARTITION_OFFSET(models_storage) + s->offset + OTA_SLOT_HDR_SIZE;
}
/* XIP pointer to a slot's model bytes (internal flash is memory-mapped at its own offset). */
static inline const uint8_t *slot_model_xip(const struct slot_def *s)
{
	return (const uint8_t *)(uintptr_t)slot_model_offset(s);
}

/* Apply a model to the matching classifier stage. Returns true if the engine accepted it. */
static bool slot_load_model(uint8_t slot, const uint8_t *buf, uint32_t len)
{
	switch (slot) {
	case MEOW_OTA_SLOT_IMU:   return clf_set_imu_model(buf, len);
	case MEOW_OTA_SLOT_AUDIO: return clf_set_audio_model(buf, len);
	default:                  return false;
	}
}

/* ------------------------------- receive state machine ------------------------------- */
/* One 4 KB page of scratch for stream_flash's buffered writes. Modest on purpose (RAM is tight). */
static uint8_t   stream_buf[OTA_SLOT_HDR_SIZE];
static struct stream_flash_ctx stream;

static struct {
	bool     active;
	uint8_t  slot;
	uint32_t total_len;     /* announced model size */
	uint32_t crc32;         /* announced CRC-32/IEEE */
	uint32_t received;      /* model bytes streamed so far */
} xfer;

static const struct bt_gatt_attr *ctrl_attr;   /* CONTROL char value attr, for status notifies */

static void ota_notify_status(uint8_t status)
{
	if (ctrl_attr) {
		(void)bt_gatt_notify(NULL, ctrl_attr, &status, sizeof(status));
	}
}

/* Drop any in-progress transfer (abort / disconnect / error). The slot keeps no valid header. */
static void xfer_reset(void)
{
	memset(&xfer, 0, sizeof(xfer));
}

/* Handle a BEGIN: validate, erase the whole slot, arm the stream writer. Returns a STATUS to notify. */
static uint8_t ota_begin(const struct meow_ota_begin *b)
{
	if (b->slot >= MEOW_OTA_SLOT_COUNT) {
		return MEOW_OTA_ST_ERR_SLOT;
	}
	const struct slot_def *s = &slots[b->slot];
	if (b->total_len == 0 || b->total_len > slot_capacity(s)) {
		LOG_WRN("BEGIN slot %u len %u exceeds capacity %u",
			b->slot, b->total_len, slot_capacity(s));
		return MEOW_OTA_ST_ERR_SIZE;
	}

	const struct flash_area *fa;
	int rc = flash_area_open(FIXED_PARTITION_ID(models_storage), &fa);
	if (rc) {
		LOG_ERR("flash_area_open failed (%d)", rc);
		return MEOW_OTA_ST_ERR_FLASH;
	}

	/* Erase ONLY the header page up front: that invalidates the old model instantly (magic gone, so
	 * load-on-boot ignores the slot) and is one ~85 ms page erase, not a multi-second whole-slot erase
	 * that would block the BT thread past the link supervision timeout. stream_flash erases each model
	 * page on demand as the bytes arrive (CONFIG_STREAM_FLASH_ERASE), spreading those erases across the
	 * write-with-response-paced transfer. A new model shorter than the old leaves stale tail bytes in
	 * the model region, but they're past hdr.len so the CRC'd load never reads them. */
	rc = flash_area_erase(fa, s->offset, OTA_SLOT_HDR_SIZE);
	if (rc) {
		LOG_ERR("erase slot %u header failed (%d)", b->slot, rc);
		flash_area_close(fa);
		return MEOW_OTA_ST_ERR_FLASH;
	}

	/* Stream into the model region (past the header page). stream_flash wants the flash device +
	 * an absolute offset within it; FIXED_PARTITION_OFFSET gives the partition base. */
	const struct device *fdev = flash_area_get_device(fa);
	uint32_t model_off = (uint32_t)FIXED_PARTITION_OFFSET(models_storage)
			   + s->offset + OTA_SLOT_HDR_SIZE;
	flash_area_close(fa);   /* stream_flash drives the device directly from here on */

	rc = stream_flash_init(&stream, fdev, stream_buf, sizeof(stream_buf),
			       model_off, slot_capacity(s), NULL);
	if (rc) {
		LOG_ERR("stream_flash_init failed (%d)", rc);
		return MEOW_OTA_ST_ERR_FLASH;
	}

	xfer.active    = true;
	xfer.slot      = b->slot;
	xfer.total_len = b->total_len;
	xfer.crc32     = b->crc32;
	xfer.received  = 0;
	LOG_INF("OTA begin: slot %u, %u bytes (crc %08x)", b->slot, b->total_len, b->crc32);
	return MEOW_OTA_ST_READY;
}

/* Handle an END: flush, verify CRC from XIP, commit the header, hot-load. Returns a STATUS. */
static uint8_t ota_end(void)
{
	if (!xfer.active) {
		return MEOW_OTA_ST_ERR_SEQ;
	}
	const struct slot_def *s = &slots[xfer.slot];

	int rc = stream_flash_buffered_write(&stream, NULL, 0, true);   /* flush remainder */
	if (rc) {
		LOG_ERR("stream flush failed (%d)", rc);
		xfer_reset();
		return MEOW_OTA_ST_ERR_FLASH;
	}
	if (xfer.received != xfer.total_len) {
		LOG_WRN("END short: got %u of %u", xfer.received, xfer.total_len);
		xfer_reset();
		return MEOW_OTA_ST_ERR_SEQ;
	}

	/* Re-read the model straight from flash (XIP) and verify it landed intact. */
	const uint8_t *model = slot_model_xip(s);
	uint32_t crc = crc32_ieee(model, xfer.total_len);
	if (crc != xfer.crc32) {
		LOG_ERR("CRC mismatch: flash %08x vs announced %08x", crc, xfer.crc32);
		xfer_reset();   /* header left unwritten -> slot stays invalid */
		return MEOW_OTA_ST_ERR_CRC;
	}

	/* Verified. Hot-load BEFORE committing the header: if the engine rejects it (arena too small),
	 * report ERR_LOAD and leave the slot invalid rather than persist a model we cannot run. */
	if (!slot_load_model(xfer.slot, model, xfer.total_len)) {
		LOG_ERR("classifier rejected slot %u model (arena too small?)", xfer.slot);
		xfer_reset();
		return MEOW_OTA_ST_ERR_LOAD;
	}

	/* Commit the header LAST , this is what makes the slot valid for load-on-boot. */
	const struct flash_area *fa;
	rc = flash_area_open(FIXED_PARTITION_ID(models_storage), &fa);
	if (rc) {
		xfer_reset();
		return MEOW_OTA_ST_ERR_FLASH;
	}
	struct meow_ota_slot_hdr hdr = {
		.magic = MEOW_OTA_SLOT_MAGIC,
		.len   = xfer.total_len,
		.crc32 = xfer.crc32,
		._rsvd = 0,
	};
	rc = flash_area_write(fa, s->offset, &hdr, sizeof(hdr));   /* header page was erased in BEGIN */
	flash_area_close(fa);
	if (rc) {
		LOG_ERR("header write failed (%d)", rc);
		xfer_reset();
		return MEOW_OTA_ST_ERR_FLASH;
	}

	LOG_INF("OTA ok: slot %u (%u bytes) committed + loaded", xfer.slot, xfer.total_len);
	xfer_reset();
	return MEOW_OTA_ST_OK;
}

/* ------------------------------- GATT callbacks ------------------------------- */

static ssize_t ctrl_write(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			  const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(attr);
	ARG_UNUSED(flags);
	if (offset != 0 || len < 1) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	const uint8_t *p = buf;
	uint8_t op = p[0];
	uint8_t status;

	switch (op) {
	case MEOW_OTA_OP_BEGIN: {
		struct meow_ota_begin b;
		if (len < 1 + sizeof(b)) {
			status = MEOW_OTA_ST_ERR_SEQ;
			break;
		}
		memcpy(&b, p + 1, sizeof(b));   /* copy out , the write buffer may be unaligned */
		status = ota_begin(&b);
		if (status != MEOW_OTA_ST_READY) {
			xfer_reset();   /* a failed BEGIN leaves no active transfer */
		}
		break;
	}
	case MEOW_OTA_OP_END:
		status = ota_end();
		break;
	case MEOW_OTA_OP_ABORT:
		LOG_INF("OTA abort");
		xfer_reset();
		status = MEOW_OTA_ST_IDLE;
		break;
	default:
		status = MEOW_OTA_ST_ERR_SEQ;
		break;
	}

	ota_notify_status(status);
	return len;
}

static ssize_t data_write(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			  const void *buf, uint16_t len, uint16_t offset, uint8_t flags)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(attr);
	ARG_UNUSED(flags);
	if (offset != 0) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	if (!xfer.active) {
		ota_notify_status(MEOW_OTA_ST_ERR_SEQ);
		return len;   /* ack the write; client sees the error via the status notify */
	}
	if (len == 0) {
		return len;
	}
	if (xfer.received + len > xfer.total_len) {
		LOG_WRN("DATA overrun: %u + %u > %u", xfer.received, len, xfer.total_len);
		xfer_reset();
		ota_notify_status(MEOW_OTA_ST_ERR_SEQ);
		return len;
	}

	int rc = stream_flash_buffered_write(&stream, buf, len, false);
	if (rc) {
		LOG_ERR("stream write failed (%d)", rc);
		xfer_reset();
		ota_notify_status(MEOW_OTA_ST_ERR_FLASH);
		return len;
	}
	xfer.received += len;
	/* No per-chunk status notify: each DATA write is paced by its own write-response (flow control),
	 * and the status channel stays silent during streaming so the client's next milestone wait (END
	 * -> OK) can't be confused by a stale RECEIVING notify. Status is only sent at BEGIN/END/errors. */
	return len;
}

static void ctrl_ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
	ARG_UNUSED(attr);
	LOG_INF("OTA status notifications %s",
		(value == BT_GATT_CCC_NOTIFY) ? "ON" : "off");
}

/* Drop a partial transfer if the station vanishes mid-push. The slot has no valid header yet, so
 * load-on-boot ignores it , no half-written model ever becomes live. */
static void ota_disconnected(struct bt_conn *conn, uint8_t reason)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);
	if (xfer.active) {
		LOG_INF("OTA: central gone mid-transfer , discarding partial slot %u", xfer.slot);
		xfer_reset();
	}
}
BT_CONN_CB_DEFINE(ota_conn_cbs) = { .disconnected = ota_disconnected };

/* The OTA GATT service. CONTROL = write + notify (status), DATA = write-with-response (the response
 * is the natural flow control that paces the client while flash erases/programs). */
static struct bt_uuid_128 ota_svc_uuid  = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x4d656f77, 0x0b01, 0x4175, 0x6469, 0x6f0053657600));
static struct bt_uuid_128 ota_ctrl_uuid = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x4d656f77, 0x0b02, 0x4175, 0x6469, 0x6f0043747200));
static struct bt_uuid_128 ota_data_uuid = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x4d656f77, 0x0b03, 0x4175, 0x6469, 0x6f0044617400));

BT_GATT_SERVICE_DEFINE(meow_ota_svc,
	BT_GATT_PRIMARY_SERVICE(&ota_svc_uuid),
	BT_GATT_CHARACTERISTIC(&ota_ctrl_uuid.uuid,
			       BT_GATT_CHRC_WRITE | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_WRITE, NULL, ctrl_write, NULL),
	BT_GATT_CCC(ctrl_ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),
	BT_GATT_CHARACTERISTIC(&ota_data_uuid.uuid,
			       BT_GATT_CHRC_WRITE,
			       BT_GATT_PERM_WRITE, NULL, data_write, NULL),
);

/* The CONTROL value attribute is index 2 (0 = service, 1 = char decl, 2 = char value). */
static int ota_attr_init(void)
{
	ctrl_attr = &meow_ota_svc.attrs[2];
	return 0;
}
SYS_INIT(ota_attr_init, APPLICATION, 0);

/* ------------------------------- load-on-boot ------------------------------- */

void ota_load_stored_models(void)
{
	for (uint8_t i = 0; i < MEOW_OTA_SLOT_COUNT; i++) {
		const struct slot_def *s = &slots[i];

		/* The header lives at the start of the slot (XIP-readable like the model). */
		const struct meow_ota_slot_hdr *hdr =
			(const struct meow_ota_slot_hdr *)(uintptr_t)
			((uint32_t)FIXED_PARTITION_OFFSET(models_storage) + s->offset);

		if (hdr->magic != MEOW_OTA_SLOT_MAGIC) {
			LOG_INF("slot %u empty (no model)", i);
			continue;
		}
		if (hdr->len == 0 || hdr->len > slot_capacity(s)) {
			LOG_WRN("slot %u header len %u invalid , ignoring", i, hdr->len);
			continue;
		}

		const uint8_t *model = slot_model_xip(s);
		uint32_t crc = crc32_ieee(model, hdr->len);
		if (crc != hdr->crc32) {
			LOG_WRN("slot %u CRC %08x != header %08x , ignoring", i, crc, hdr->crc32);
			continue;
		}

		if (slot_load_model(i, model, hdr->len)) {
			LOG_INF("slot %u loaded: %u bytes from flash", i, hdr->len);
		} else {
			LOG_ERR("slot %u model present but classifier rejected it", i);
		}
	}
}
