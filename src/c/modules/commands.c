#include "commands.h"

#include "../windows/main_window.h"

typedef struct {
  const char *label;
  const char *command;  // Full command string sent to JS
} BodyOption;

static const BodyOption ENGINE_START_OPTIONS[] = {{"1 min", "engine-start:1"},
                                                  {"3 min", "engine-start:3"},
                                                  {"5 min", "engine-start:5"},
                                                  {"10 min", "engine-start:10"},
                                                  {"15 min", "engine-start:15"}};

#define NUM_COMMANDS 9

typedef struct {
  uint32_t bit;
  const char *label;
  const char *path;
  bool confirm;
  const BodyOption *options;
  int num_options;
} Command;

static const Command COMMANDS[NUM_COMMANDS] = {
    {CMD_FLASH, "Flash Lights", "flash", false, NULL, 0},
    {CMD_HONK, "Honk", "honk", true, NULL, 0},
    {CMD_HONK_FLASH, "Honk + Flash", "honk-flash", true, NULL, 0},
    {CMD_LOCK, "Lock", "lock", false, NULL, 0},
    {CMD_UNLOCK, "Unlock", "unlock", true, NULL, 0},
    {CMD_CLIMATE_START, "Climate On", "climatization-start", true, NULL, 0},
    {CMD_CLIMATE_STOP, "Climate Off", "climatization-stop", false, NULL, 0},
    {CMD_ENGINE_START, "Engine Start", "engine-start", false, ENGINE_START_OPTIONS,
     sizeof(ENGINE_START_OPTIONS) / sizeof(ENGINE_START_OPTIONS[0])},
    {CMD_ENGINE_STOP, "Engine Stop", "engine-stop", false, NULL, 0},
};

static ActionMenu *s_menu;
static ActionMenuLevel *s_level;
static uint32_t s_available = 0xFFFFFFFF;  // All available by default.

// Callbacks

static void on_action(ActionMenu *menu, const ActionMenuItem *item, void *ctx) {
  DictionaryIterator *iter;
  if (app_message_outbox_begin(&iter) == APP_MSG_OK) {
    dict_write_cstring(iter, MESSAGE_KEY_COMMAND,
                       (const char *)action_menu_item_get_action_data(item));
    app_message_outbox_send();
  }
  main_window_set_status("Sending...");
}

static void on_closed(ActionMenu *menu, const ActionMenuItem *item, void *ctx) {
  s_menu = NULL;
}

// Public API

void commands_set_available(uint32_t bitmask) {
  s_available = bitmask;
}

void commands_open_menu(void) {
  int count = 0;
  for (int i = 0; i < NUM_COMMANDS; i++) {
    if (s_available & COMMANDS[i].bit)
      count++;
  }
  if (count == 0)
    count = 1;

  s_level = action_menu_level_create(count);
  for (int i = 0; i < NUM_COMMANDS; i++) {
    if (!(s_available & COMMANDS[i].bit))
      continue;

    if (COMMANDS[i].options) {
      // Command with body: option selection → confirm
      int n = COMMANDS[i].num_options;
      ActionMenuLevel *opts = action_menu_level_create(n);
      for (int t = 0; t < n; t++) {
        ActionMenuLevel *confirm = action_menu_level_create(1);
        action_menu_level_add_action(confirm, "Confirm", on_action,
                                     (void *)COMMANDS[i].options[t].command);
        action_menu_level_add_child(opts, confirm, COMMANDS[i].options[t].label);
      }
      action_menu_level_add_child(s_level, opts, COMMANDS[i].label);
    } else if (COMMANDS[i].confirm) {
      // Command with confirmation
      ActionMenuLevel *child = action_menu_level_create(1);
      action_menu_level_add_action(child, "Confirm", on_action, (void *)COMMANDS[i].path);
      action_menu_level_add_child(s_level, child, COMMANDS[i].label);
    } else {
      // Simple command
      action_menu_level_add_action(s_level, COMMANDS[i].label, on_action, (void *)COMMANDS[i].path);
    }
  }

  ActionMenuConfig cfg = (ActionMenuConfig){
      .root_level = s_level,
      .colors =
          {
              .background = PBL_IF_COLOR_ELSE(GColorCobaltBlue, GColorWhite),
              .foreground = GColorWhite,
          },
      .align = ActionMenuAlignCenter,
      .did_close = on_closed,
  };
  s_menu = action_menu_open(&cfg);
}
