/*
 * Audio/IMU streaming , the decoupled reader/sender pair.
 *
 * While a station is subscribed the collar streams continuously in 100 ms frames on the audio
 * characteristic. A reader thread drives the mic + IMU and assembles frames; a separate sender
 * thread drains them to BLE. Decoupling the two keeps the mic's real-time DMA off the BLE link
 * (see streaming.c). Both threads are defined statically , there is no runtime API to call.
 */
#pragma once
