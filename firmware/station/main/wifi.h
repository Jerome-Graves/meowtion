#pragma once
/* wifi.h , station WiFi bring-up + time sync. */
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"

#define WIFI_CONNECTED_BIT BIT0

/* Event group signalled when the station has an IP. main's recovery loop waits on this. */
extern EventGroupHandle_t s_wifi_eg;

bool wifi_init_sta(void);   /* true if connected within ~45 s, false to trigger re-provisioning */
void wait_for_time(void);   /* block (up to ~15 s) until SNTP gives real wall-clock time */
