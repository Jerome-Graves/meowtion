/*
 * weather.c , local weather feed (Open-Meteo).
 *
 * Polls the current conditions for the provisioned lat/lon and relays a compact line to the
 * owner's account (current + history), so the dashboard can correlate cat behaviour with weather.
 */
#include "weather.h"
#include "config.h"
#include "cloud.h"

#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "cJSON.h"

static const char *TAG = "meowtion-wx";

/* Map an Open-Meteo WMO weather code (+ precipitation) to one of our coarse condition labels. */
static const char *condition_for(int code, double precip)
{
    if (code >= 95) return "thunder";
    if (code >= 71 && code <= 77) return "snow";
    if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82) || precip > 0) return "rain";
    if (code >= 1 && code <= 3) return "cloudy";
    if (code == 45 || code == 48) return "fog";
    return "clear";
}

void poll_weather(void)
{
    char url[320];
    snprintf(url, sizeof url,
             "https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f"
             "&current=temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
             g_lat, g_lon);
    static char resp[1024];
    if (http_do(HTTP_METHOD_GET, url, NULL, resp, sizeof resp) != 200) { ESP_LOGE(TAG, "open-meteo failed"); return; }
    cJSON *j = cJSON_Parse(resp);
    if (!j) return;
    const cJSON *cur = cJSON_GetObjectItem(j, "current");
    if (cur) {
        double temp   = cJSON_GetObjectItem(cur, "temperature_2m") ? cJSON_GetObjectItem(cur, "temperature_2m")->valuedouble : 0;
        double precip = cJSON_GetObjectItem(cur, "precipitation")  ? cJSON_GetObjectItem(cur, "precipitation")->valuedouble  : 0;
        int    hum    = cJSON_GetObjectItem(cur, "relative_humidity_2m") ? cJSON_GetObjectItem(cur, "relative_humidity_2m")->valueint : 0;
        double wind   = cJSON_GetObjectItem(cur, "wind_speed_10m") ? cJSON_GetObjectItem(cur, "wind_speed_10m")->valuedouble : 0;
        int    code   = cJSON_GetObjectItem(cur, "weather_code")   ? cJSON_GetObjectItem(cur, "weather_code")->valueint   : 0;
        const char *cond = condition_for(code, precip);
        bool raining = (strcmp(cond, "rain") == 0 || strcmp(cond, "thunder") == 0);
        int64_t ts = now_ms();
        char body[256], suffix[64];
        (void)hum; (void)wind;   /* not stored in the stripped-down schema */
        snprintf(body, sizeof body, "{\"ts\":%lld,\"tempC\":%.1f,\"condition\":\"%s\",\"raining\":%s}",
                 (long long)ts, temp, cond, raining ? "true" : "false");
        dev_write(HTTP_METHOD_PUT, "/weather/current", body);
        snprintf(body, sizeof body, "{\"tempC\":%.1f,\"condition\":\"%s\",\"raining\":%s}",
                 temp, cond, raining ? "true" : "false");
        snprintf(suffix, sizeof suffix, "/weather/history/%lld", (long long)ts);
        dev_write(HTTP_METHOD_PUT, suffix, body);
        ESP_LOGI(TAG, "weather %.1fC %s", temp, cond);
    }
    cJSON_Delete(j);
}
