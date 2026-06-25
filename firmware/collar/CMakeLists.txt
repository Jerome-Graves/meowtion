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
    src/imu.c)
target_include_directories(app PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../common)   # shared meow_protocol.h
