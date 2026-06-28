#pragma once
/* cloud.h , Firebase RTDB + binary upload HTTP layer (the only HTTP in the firmware). */
#include <stdint.h>
#include "esp_http_client.h"

/* Response-capture buffer passed through the HTTP event handler. */
typedef struct { char *buf; int len; int cap; } resp_t;

/* Generic request. out/out_cap optional (NULL to ignore the body). Returns HTTP status, or -1. */
int http_do(esp_http_client_method_t method, const char *url, const char *body, char *out, int out_cap);

/* RTDB access under /users/{owner}/devices/{token}/<suffix>. */
int dev_write(esp_http_client_method_t method, const char *suffix, const char *json);
int dev_read(const char *suffix, char *out, int out_cap);

/* POST a raw binary body. out/out_cap optional: when given, captures the response body.
 * auth optional: when non-NULL, sent as an "Authorization: Bearer <auth>" header so the device
 * token stays out of the URL/query string (which would otherwise land in server/proxy logs). */
int http_post_bin(const char *url, const uint8_t *body, int len, const char *ctype,
                  const char *auth, char *out, int out_cap);
