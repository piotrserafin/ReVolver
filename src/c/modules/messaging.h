#pragma once

#include <pebble.h>

void messaging_init(void);
bool messaging_send_command(const char *cmd);
void messaging_vibrate(bool success);
