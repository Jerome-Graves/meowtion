#pragma once
/* weather.h , local weather feed (Open-Meteo) relayed to the owner's account. */

void poll_weather(void);   /* fetch current conditions for the provisioned lat/lon and publish */
