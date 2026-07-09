#pragma once

#include <pebble.h>

void main_window_push(void);

void main_window_set_vin(const char *vin);
void main_window_set_info(const char *info);
void main_window_set_car_status(const char *status);
void main_window_set_status(const char *status);
void main_window_show_temp_status(const char *text);
