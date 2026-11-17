#pragma once

#include <pebble.h>

// Runs the action chosen in settings when the app is opened from a Quick Launch button.
void quick_launch_init(void);
void quick_launch_set_action(const char *cmd);
void quick_launch_set_exit(bool exit);
void quick_launch_on_js_ready(void);
void quick_launch_on_result(void);
bool quick_launch_is_busy(void);
