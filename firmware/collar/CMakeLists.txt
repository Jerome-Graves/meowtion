cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(meowtion_collar)

target_sources(app PRIVATE
    src/main.c
    src/ble.c
    src/audio.c
    src/streaming.c
    src/battery.c
    src/classifier.c
    src/production.c            # production mode: real on-device classification -> telemetry
    src/imu.c
    src/ota.c                   # Phase-3 OTA model delivery: BLE -> flash slots -> XIP load
    src/tflm_classifier.cpp)   # TFLM inference backend , strong overrides of the cascade hooks
target_include_directories(app PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../common)   # shared meow_protocol.h
