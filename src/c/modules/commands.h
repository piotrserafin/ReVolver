#pragma once

#include <pebble.h>

// Command bit flags (must match CMD_BITS in JS)
#define CMD_FLASH (1 << 0)
#define CMD_HONK (1 << 1)
#define CMD_HONK_FLASH (1 << 2)
#define CMD_LOCK (1 << 3)
#define CMD_UNLOCK (1 << 4)
#define CMD_CLIMATE_START (1 << 5)
#define CMD_CLIMATE_STOP (1 << 6)
#define CMD_ENGINE_START (1 << 7)
#define CMD_ENGINE_STOP (1 << 8)

void commands_set_available(uint32_t bitmask);
void commands_open_menu(void);
