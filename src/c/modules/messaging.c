#include "messaging.h"

#include "../windows/main_window.h"
#include "commands.h"

static bool s_vibrate = true;

static void vibrate(bool success) {
  if (!s_vibrate)
    return;
  static const uint32_t ok_seg[] = {100};
  static const uint32_t err_seg[] = {100, 100, 100};
  VibePattern pat = success ? (VibePattern){.durations = ok_seg, .num_segments = 1}
                            : (VibePattern){.durations = err_seg, .num_segments = 3};
  vibes_enqueue_custom_pattern(pat);
}

static void inbox_received(DictionaryIterator *iter, void *ctx) {
  Tuple *t;

  if ((t = dict_find(iter, MESSAGE_KEY_VIN))) {
    main_window_set_vin(t->value->cstring);
  }

  if ((t = dict_find(iter, MESSAGE_KEY_STATUS_MSG))) {
    main_window_set_status(t->value->cstring);
  }

  if ((t = dict_find(iter, MESSAGE_KEY_CAR_STATUS))) {
    main_window_set_car_status(t->value->cstring);
  }

  if ((t = dict_find(iter, MESSAGE_KEY_CAR_INFO))) {
    main_window_set_info(t->value->cstring);
  }

  if ((t = dict_find(iter, MESSAGE_KEY_AVAILABLE_CMDS))) {
    commands_set_available((uint32_t)t->value->int32);
  }

  if ((t = dict_find(iter, MESSAGE_KEY_VIBRATE))) {
    s_vibrate = (bool)t->value->int32;
    persist_write_bool(MESSAGE_KEY_VIBRATE, s_vibrate);
  }

  if ((t = dict_find(iter, MESSAGE_KEY_COMMAND_RESULT))) {
    const char *str = t->value->cstring;
    bool success = (str[0] == '+');
    main_window_show_temp_status(str + 1);
    vibrate(success);
  }
}

// Public API

void messaging_init(void) {
  if (persist_exists(MESSAGE_KEY_VIBRATE)) {
    s_vibrate = persist_read_bool(MESSAGE_KEY_VIBRATE);
  }

  app_message_register_inbox_received(inbox_received);
  app_message_open(1024, 256);
}
