#include "main_window.h"

#include "../modules/commands.h"

// Persist keys
#define PERSIST_VIN 1
#define PERSIST_INFO 2
#define PERSIST_CAR 3

static Window *s_window;
static TextLayer *s_title_layer, *s_vin_layer, *s_info_layer;
static TextLayer *s_car_layer, *s_status_layer, *s_hint_layer;
static AppTimer *s_revert_timer;

static char s_vin[32];
static char s_info[32];
static char s_car[48];
static char s_status[32];

static void load_persisted(void) {
  if (persist_exists(PERSIST_VIN)) {
    persist_read_string(PERSIST_VIN, s_vin, sizeof(s_vin));
  } else {
    snprintf(s_vin, sizeof(s_vin), "Not set");
  }
  if (persist_exists(PERSIST_INFO)) {
    persist_read_string(PERSIST_INFO, s_info, sizeof(s_info));
  }
  if (persist_exists(PERSIST_CAR)) {
    persist_read_string(PERSIST_CAR, s_car, sizeof(s_car));
  }
  snprintf(s_status, sizeof(s_status), "Connecting...");
}

static TextLayer *make_text(Layer *parent, GRect frame, const char *text, GFont font,
                            GTextAlignment align, GColor color) {
  TextLayer *tl = text_layer_create(frame);
  text_layer_set_text(tl, text);
  text_layer_set_font(tl, font);
  text_layer_set_text_alignment(tl, align);
  text_layer_set_background_color(tl, GColorClear);
  text_layer_set_text_color(tl, color);
  layer_add_child(parent, text_layer_get_layer(tl));
  return tl;
}

static void revert_status(void *ctx) {
  s_revert_timer = NULL;
  snprintf(s_status, sizeof(s_status), "Ready");
  if (s_status_layer)
    text_layer_set_text(s_status_layer, s_status);
}

void main_window_set_vin(const char *vin) {
  snprintf(s_vin, sizeof(s_vin), "%s", vin);
  persist_write_string(PERSIST_VIN, s_vin);
  if (s_vin_layer)
    text_layer_set_text(s_vin_layer, s_vin);
}

void main_window_set_info(const char *info) {
  snprintf(s_info, sizeof(s_info), "%s", info);
  persist_write_string(PERSIST_INFO, s_info);
  if (s_info_layer)
    text_layer_set_text(s_info_layer, s_info);
}

void main_window_set_car_status(const char *status) {
  snprintf(s_car, sizeof(s_car), "%s", status);
  persist_write_string(PERSIST_CAR, s_car);
  if (s_car_layer)
    text_layer_set_text(s_car_layer, s_car);
}

void main_window_set_status(const char *text) {
  if (s_revert_timer) {
    app_timer_cancel(s_revert_timer);
    s_revert_timer = NULL;
  }
  snprintf(s_status, sizeof(s_status), "%s", text);
  if (s_status_layer)
    text_layer_set_text(s_status_layer, s_status);
}

void main_window_show_temp_status(const char *text) {
  if (s_revert_timer)
    app_timer_cancel(s_revert_timer);
  snprintf(s_status, sizeof(s_status), "%s", text);
  if (s_status_layer)
    text_layer_set_text(s_status_layer, s_status);
  s_revert_timer = app_timer_register(3000, revert_status, NULL);
}

// Window Handlers

static void on_select(ClickRecognizerRef ref, void *ctx) {
  commands_open_menu();
}

static void on_up(ClickRecognizerRef ref, void *ctx) {
  // Send refresh request to JS
  DictionaryIterator *iter;
  if (app_message_outbox_begin(&iter) == APP_MSG_OK) {
    dict_write_cstring(iter, MESSAGE_KEY_COMMAND, "refresh");
    app_message_outbox_send();
  }
  main_window_set_status("Refreshing...");
}

static void click_config(void *ctx) {
  window_single_click_subscribe(BUTTON_ID_SELECT, on_select);
  window_single_click_subscribe(BUTTON_ID_UP, on_up);
}

static void window_load(Window *w) {
  Layer *root = window_get_root_layer(w);
  GRect b = layer_get_bounds(root);
  window_set_background_color(w, GColorBlack);

  int x = PBL_IF_ROUND_ELSE(28, 8);
  int width = b.size.w - 2 * x;
  int y = PBL_IF_ROUND_ELSE(20, 6);

  s_title_layer =
      make_text(root, GRect(x, y, width, 34), "ReVolver",
                fonts_get_system_font(FONT_KEY_GOTHIC_28_BOLD), GTextAlignmentCenter, GColorWhite);

  s_vin_layer =
      make_text(root, GRect(x, y + 38, width, 26), s_vin,
                fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD), GTextAlignmentCenter, GColorWhite);

  s_info_layer =
      make_text(root, GRect(x, y + 64, width, 22), s_info,
                fonts_get_system_font(FONT_KEY_GOTHIC_18), GTextAlignmentCenter, GColorLightGray);

  s_car_layer = make_text(root, GRect(x, y + 86, width, 22), s_car,
                          fonts_get_system_font(FONT_KEY_GOTHIC_18_BOLD), GTextAlignmentCenter,
                          PBL_IF_COLOR_ELSE(GColorMediumSpringGreen, GColorWhite));

  s_status_layer = make_text(root, GRect(x, y + 108, width, 28), s_status,
                             fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD), GTextAlignmentCenter,
                             GColorLightGray);

  int hint_y = b.size.h - PBL_IF_ROUND_ELSE(38, 22);
  s_hint_layer =
      make_text(root, GRect(x, hint_y, width, 18), "SELECT \xe2\x86\x92 commands",
                fonts_get_system_font(FONT_KEY_GOTHIC_14), GTextAlignmentCenter, GColorDarkGray);

  window_set_click_config_provider(w, click_config);
}

static void window_unload(Window *w) {
  text_layer_destroy(s_title_layer);
  text_layer_destroy(s_vin_layer);
  text_layer_destroy(s_info_layer);
  text_layer_destroy(s_car_layer);
  text_layer_destroy(s_status_layer);
  text_layer_destroy(s_hint_layer);
  if (s_revert_timer)
    app_timer_cancel(s_revert_timer);
}

// Public API

void main_window_push(void) {
  load_persisted();
  s_window = window_create();
  window_set_window_handlers(s_window, (WindowHandlers){
                                           .load = window_load,
                                           .unload = window_unload,
                                       });
  window_stack_push(s_window, true);
}
