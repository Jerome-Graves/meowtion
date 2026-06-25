/*
 * config.c , provisioned identity and credentials for the station.
 *
 * Owns the provisioned globals (WiFi, owner, per-device token, name, weather location) and
 * their persistence in NVS, plus the USB-serial provisioning flow that fills them. No network
 * or BLE here: this module is only about "who am I and how do I reach my owner's account".
 */
#include "config.h"

#include <string.h>
#include <stdio.h>
#include <time.h>
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_log.h"
#include "driver/usb_serial_jtag.h"
#include "cJSON.h"

static const char *TAG = "meowtion-cfg";

/* Provisioned identity. Declared extern in config.h; defined here as the single owner. */
char   g_ssid[64], g_pass[64], g_owner[64], g_token[96], g_name[64] = "Station";
char   g_device_id[16];                  /* MAC hex , just for the picker handshake */
double g_lat = DEFAULT_LAT, g_lon = DEFAULT_LON;

/* ---------------- shared helpers ---------------- */
void setstr(char *dst, size_t cap, const char *src) { snprintf(dst, cap, "%s", src ? src : ""); }
int64_t now_ms(void) { return (int64_t)time(NULL) * 1000; }

/* ---------------- NVS ---------------- */
bool nvs_load(void)
{
    nvs_handle_t h;
    if (nvs_open("meow", NVS_READONLY, &h) != ESP_OK) return false;
    size_t l;
    bool ok = true;
    l = sizeof g_ssid;  if (nvs_get_str(h, "ssid",  g_ssid,  &l) != ESP_OK) ok = false;
    l = sizeof g_pass;  if (nvs_get_str(h, "pass",  g_pass,  &l) != ESP_OK) ok = false;
    l = sizeof g_owner; if (nvs_get_str(h, "owner", g_owner, &l) != ESP_OK) ok = false;
    l = sizeof g_token; if (nvs_get_str(h, "token", g_token, &l) != ESP_OK) ok = false;
    l = sizeof g_name;  nvs_get_str(h, "name", g_name, &l);
    int64_t bits;
    if (nvs_get_i64(h, "lat", &bits) == ESP_OK) memcpy(&g_lat, &bits, sizeof(double));
    if (nvs_get_i64(h, "lon", &bits) == ESP_OK) memcpy(&g_lon, &bits, sizeof(double));
    nvs_close(h);
    return ok;
}

static void nvs_save(const char *ssid, const char *pass, const char *owner,
                     const char *token, const char *name, double lat, double lon)
{
    nvs_handle_t h;
    if (nvs_open("meow", NVS_READWRITE, &h) != ESP_OK) return;
    nvs_set_str(h, "ssid", ssid);  nvs_set_str(h, "pass", pass);  nvs_set_str(h, "owner", owner);
    nvs_set_str(h, "token", token); nvs_set_str(h, "name", name);
    int64_t bits;
    memcpy(&bits, &lat, sizeof(double)); nvs_set_i64(h, "lat", bits);
    memcpy(&bits, &lon, sizeof(double)); nvs_set_i64(h, "lon", bits);
    nvs_commit(h);
    nvs_close(h);
    setstr(g_ssid, sizeof g_ssid, ssid);   setstr(g_pass, sizeof g_pass, pass);
    setstr(g_owner, sizeof g_owner, owner); setstr(g_token, sizeof g_token, token);
    setstr(g_name, sizeof g_name, name);    g_lat = lat; g_lon = lon;
}

/* ---------------- USB serial provisioning ---------------- */
int serial_read_line(char *buf, int cap, int timeout_ms)
{
    int n = 0, waited = 0;
    while (n < cap - 1) {
        uint8_t ch;
        int r = usb_serial_jtag_read_bytes(&ch, 1, pdMS_TO_TICKS(100));
        if (r == 1) {
            if (ch == '\n' || ch == '\r') { if (n > 0) break; else continue; }
            buf[n++] = ch;
        } else if (timeout_ms >= 0 && (waited += 100) >= timeout_ms) {
            break;
        }
    }
    buf[n] = 0;
    return n;
}

/* Parse one provisioning JSON line and save it to NVS. Returns true if it was valid. */
bool try_provision(const char *line)
{
    cJSON *j = cJSON_Parse(line);
    if (!j) { printf("MEOW> error invalid-json\n"); return false; }
    const cJSON *ssid = cJSON_GetObjectItem(j, "ssid");
    const cJSON *pass = cJSON_GetObjectItem(j, "pass");
    const cJSON *owner = cJSON_GetObjectItem(j, "owner");
    const cJSON *token = cJSON_GetObjectItem(j, "token");
    bool ok = cJSON_IsString(ssid) && cJSON_IsString(pass) && cJSON_IsString(owner) && cJSON_IsString(token);
    if (ok) {
        const cJSON *name = cJSON_GetObjectItem(j, "name");
        const cJSON *lat = cJSON_GetObjectItem(j, "lat");
        const cJSON *lon = cJSON_GetObjectItem(j, "lon");
        nvs_save(ssid->valuestring, pass->valuestring, owner->valuestring, token->valuestring,
                 cJSON_IsString(name) ? name->valuestring : "Station",
                 cJSON_IsNumber(lat) ? lat->valuedouble : DEFAULT_LAT,
                 cJSON_IsNumber(lon) ? lon->valuedouble : DEFAULT_LON);
        printf("MEOW> provisioned\n");
    } else {
        printf("MEOW> error need-ssid-pass-owner-token\n");
    }
    cJSON_Delete(j);
    return ok;
}

void provision_mode(void)
{
    char line[512];
    ESP_LOGW(TAG, "unprovisioned , waiting for config over serial");
    while (1) {
        printf("MEOW> meowtion id=%s awaiting-provisioning\n", g_device_id);
        if (serial_read_line(line, sizeof line, 5000) > 0 && try_provision(line)) return;
    }
}
