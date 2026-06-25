idf_component_register(
    SRCS "main.c" "config.c" "board.c" "wifi.c" "cloud.c" "weather.c" "ble.c"
    INCLUDE_DIRS "." "../../common"
    REQUIRES esp_wifi esp_http_client nvs_flash esp_event esp_netif esp-tls json lwip esp_driver_usb_serial_jtag esp_hw_support esp_adc esp_driver_gpio bt
)
