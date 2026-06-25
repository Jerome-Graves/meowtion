#pragma once
/*
 * PUBLIC project config , NOT secrets. The device does not log in to Firebase at all:
 * it writes to /users/{owner}/devices/{token}/... over HTTPS, and the database rule
 * allows it because the token (provisioned over USB into NVS) is registered to that owner.
 *
 * WiFi, owner, token, and weather location are all provisioned over USB serial. There is
 * no API key here.
 */
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

#define DB_URL   "https://meowtion-app-default-rtdb.europe-west1.firebasedatabase.app"

/* Authenticated clip ingest. Audio/IMU clips are POSTed to the upload_clip Cloud Function
 * (it validates the device token and writes them into the owner's training area), so the
 * station never touches Firebase Storage directly. */
#define UPLOAD_CLIP_URL "https://europe-west1-meowtion-app.cloudfunctions.net/upload_clip"

#define DEFAULT_LAT 50.8     /* fallback if the browser didn't pass a location */
#define DEFAULT_LON -0.1

/* Provisioned identity (defined in config.c). */
extern char   g_ssid[64], g_pass[64], g_owner[64], g_token[96], g_name[64];
extern char   g_device_id[16];     /* MAC hex , just for the picker handshake */
extern double g_lat, g_lon;

/* shared helpers */
void    setstr(char *dst, size_t cap, const char *src);
int64_t now_ms(void);

/* NVS persistence + USB-serial provisioning */
bool nvs_load(void);
int  serial_read_line(char *buf, int cap, int timeout_ms);
bool try_provision(const char *line);
void provision_mode(void);
