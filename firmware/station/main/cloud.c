/*
 * cloud.c , the only HTTP layer in the firmware.
 *
 * Wraps esp_http_client for two jobs: Firebase RTDB reads/writes under the device's own path
 * (/users/{owner}/devices/{token}/...), and binary POSTs (audio/IMU clips to the upload_clip
 * Cloud Function). No auth header: the database rule authorises writes because the path's token
 * is registered to the owner. Every other module routes its network access through here.
 */
#include "cloud.h"
#include "config.h"

#include <string.h>
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_log.h"

static const char *TAG = "meowtion-cloud";

/* Accumulates the response body into the caller's buffer (when one was supplied). */
static esp_err_t http_evt(esp_http_client_event_t *e)
{
    if (e->event_id == HTTP_EVENT_ON_DATA && e->user_data) {
        resp_t *r = (resp_t *)e->user_data;
        if (r->buf && r->len + e->data_len < r->cap - 1) {
            memcpy(r->buf + r->len, e->data, e->data_len);
            r->len += e->data_len;
            r->buf[r->len] = 0;
        }
    }
    return ESP_OK;
}

int http_do(esp_http_client_method_t method, const char *url, const char *body, char *out, int out_cap)
{
    resp_t r = { .buf = out, .len = 0, .cap = out_cap };
    if (out && out_cap) out[0] = 0;
    esp_http_client_config_t cfg = {
        .url = url, .method = method, .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = 10000, .event_handler = http_evt, .user_data = (out ? &r : NULL),
    };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (body) {
        esp_http_client_set_header(c, "Content-Type", "application/json");
        esp_http_client_set_post_field(c, body, strlen(body));
    }
    esp_err_t err = esp_http_client_perform(c);
    int status = (err == ESP_OK) ? esp_http_client_get_status_code(c) : -1;
    if (err != ESP_OK) ESP_LOGE(TAG, "http: %s", esp_err_to_name(err));
    esp_http_client_cleanup(c);
    return status;
}

/* write under /users/{owner}/devices/{token}/<suffix> */
int dev_write(esp_http_client_method_t method, const char *suffix, const char *json)
{
    static char url[640];
    snprintf(url, sizeof url, "%s/users/%s/devices/%s%s.json", DB_URL, g_owner, g_token, suffix);
    return http_do(method, url, json, NULL, 0);
}

/* read from /users/{owner}/devices/{token}/<suffix> (token in the path authorises it) */
int dev_read(const char *suffix, char *out, int out_cap)
{
    static char url[640];
    snprintf(url, sizeof url, "%s/users/%s/devices/%s%s.json", DB_URL, g_owner, g_token, suffix);
    return http_do(HTTP_METHOD_GET, url, NULL, out, out_cap);
}

/* POST a raw binary body (a clip). When out != NULL, the response body is captured into it so the
 * caller can parse the Cloud Function's JSON reply (e.g. the stored clip path). */
int http_post_bin(const char *url, const uint8_t *body, int len, const char *ctype,
                  char *out, int out_cap)
{
    resp_t r = { .buf = out, .len = 0, .cap = out_cap };
    if (out && out_cap) out[0] = 0;
    esp_http_client_config_t cfg = {
        .url = url, .method = HTTP_METHOD_POST, .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms = 20000, .event_handler = http_evt, .user_data = (out ? &r : NULL),
    };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    esp_http_client_set_header(c, "Content-Type", ctype);
    esp_http_client_set_post_field(c, (const char *)body, len);
    esp_err_t err = esp_http_client_perform(c);
    int status = (err == ESP_OK) ? esp_http_client_get_status_code(c) : -1;
    if (err != ESP_OK) ESP_LOGE(TAG, "upload http: %s", esp_err_to_name(err));
    esp_http_client_cleanup(c);
    return status;
}
