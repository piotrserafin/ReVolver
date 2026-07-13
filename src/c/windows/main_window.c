#include "main_window.h"

#include "../modules/commands.h"

// Persist keys
#define PERSIST_INFO 1

// Spinner
#define SPINNER_SIZE 40
#define SPINNER_INTERVAL_MS 80
#define SPINNER_STEP (TRIG_MAX_ANGLE / 12)

static Window *s_window;
static TextLayer *s_info_layer;
static TextLayer *s_engine_lbl, *s_engine_layer;
static TextLayer *s_lock_lbl, *s_lock_layer;
static TextLayer *s_windows_lbl, *s_windows_layer;
static TextLayer *s_fuel_lbl, *s_fuel_layer;
static TextLayer *s_status_layer;
static Layer *s_separator_layer;
static Layer *s_spinner_layer;
static AppTimer *s_revert_timer;
static AppTimer *s_spinner_timer;

static int32_t s_spinner_angle;
static bool s_data_loaded;

static char s_info[32];
static char s_car[64];
static char s_doors[32];
static char s_engine_str[32];
static char s_windows[32];
static char s_fuel[32];
static char s_status[32];

static void parse_car_status(const char *raw) {
  // Format: "lock|engine|fuel|range|windows"
  char buf[64];
  snprintf(buf, sizeof(buf), "%s", raw);

  char *fields[5] = {NULL, NULL, NULL, NULL, NULL};
  int idx = 0;
  fields[0] = buf;
  for (char *p = buf; *p && idx < 4; p++) {
    if (*p == '|') {
      *p = '\0';
      fields[++idx] = p + 1;
    }
  }

  if (fields[0]) snprintf(s_doors, sizeof(s_doors), "%s", fields[0]);
  if (fields[1]) snprintf(s_engine_str, sizeof(s_engine_str), "%s", fields[1]);

  if (fields[4]) {
    if (strcmp(fields[4], "OK") == 0) {
      snprintf(s_windows, sizeof(s_windows), "Closed");
    } else if (fields[4][0] == '?') {
      snprintf(s_windows, sizeof(s_windows), "?");
    } else {
      snprintf(s_windows, sizeof(s_windows), "%s", fields[4]);
    }
  }

  if (fields[2]) {
    if (fields[3] && fields[3][0] != '?') {
      snprintf(s_fuel, sizeof(s_fuel), "%s (%s)", fields[2], fields[3]);
    } else {
      snprintf(s_fuel, sizeof(s_fuel), "%s", fields[2]);
    }
  }
}

static void load_persisted(void) {
  if (persist_exists(PERSIST_INFO)) {
    persist_read_string(PERSIST_INFO, s_info, sizeof(s_info));
  }
  snprintf(s_status, sizeof(s_status), "Connecting...");
}

static void update_car_layers(void) {
  if (s_lock_layer) text_layer_set_text(s_lock_layer, s_doors);
  if (s_engine_layer) text_layer_set_text(s_engine_layer, s_engine_str);
  if (s_windows_layer) text_layer_set_text(s_windows_layer, s_windows);
  if (s_fuel_layer) text_layer_set_text(s_fuel_layer, s_fuel);
}

static void set_data_visible(bool visible) {
  layer_set_hidden(text_layer_get_layer(s_engine_lbl), !visible);
  layer_set_hidden(text_layer_get_layer(s_engine_layer), !visible);
  layer_set_hidden(text_layer_get_layer(s_lock_lbl), !visible);
  layer_set_hidden(text_layer_get_layer(s_lock_layer), !visible);
  layer_set_hidden(text_layer_get_layer(s_windows_lbl), !visible);
  layer_set_hidden(text_layer_get_layer(s_windows_layer), !visible);
  layer_set_hidden(text_layer_get_layer(s_fuel_lbl), !visible);
  layer_set_hidden(text_layer_get_layer(s_fuel_layer), !visible);
}

// Spinner

static void spinner_draw(Layer *layer, GContext *ctx) {
  GRect bounds = layer_get_bounds(layer);
  graphics_context_set_stroke_color(ctx, PBL_IF_COLOR_ELSE(GColorCobaltBlue, GColorWhite));
  graphics_context_set_stroke_width(ctx, 3);

  int32_t start = s_spinner_angle;
  int32_t end = start + TRIG_MAX_ANGLE * 3 / 4;  // 270° arc
  graphics_draw_arc(ctx, grect_inset(bounds, GEdgeInsets(2)),
                    GOvalScaleModeFitCircle, start, end);
}

static void spinner_tick(void *ctx) {
  s_spinner_angle = (s_spinner_angle + SPINNER_STEP) % TRIG_MAX_ANGLE;
  if (s_spinner_layer) layer_mark_dirty(s_spinner_layer);
  s_spinner_timer = app_timer_register(SPINNER_INTERVAL_MS, spinner_tick, NULL);
}

static void spinner_start(void) {
  if (s_spinner_layer) layer_set_hidden(s_spinner_layer, false);
  if (!s_spinner_timer) {
    s_spinner_angle = 0;
    spinner_tick(NULL);
  }
}

static void spinner_stop(void) {
  if (s_spinner_timer) {
    app_timer_cancel(s_spinner_timer);
    s_spinner_timer = NULL;
  }
  if (s_spinner_layer) layer_set_hidden(s_spinner_layer, true);
}

// TextLayer helper

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

static void separator_draw(Layer *layer, GContext *ctx) {
  GRect bounds = layer_get_bounds(layer);
  graphics_context_set_stroke_color(ctx, GColorDarkGray);

  int margin = PBL_IF_ROUND_ELSE(28, 8);
  int header_h = PBL_IF_ROUND_ELSE(50, 44);
  int footer_h = PBL_IF_ROUND_ELSE(50, 50);

  graphics_draw_line(ctx, GPoint(margin, header_h), GPoint(bounds.size.w - margin, header_h));

  int bottom_y = bounds.size.h - footer_h;
  graphics_draw_line(ctx, GPoint(margin, bottom_y), GPoint(bounds.size.w - margin, bottom_y));
}

static void revert_status(void *ctx) {
  s_revert_timer = NULL;
  snprintf(s_status, sizeof(s_status), "Ready");
  if (s_status_layer) text_layer_set_text(s_status_layer, s_status);
}

// Public API

void main_window_set_info(const char *info) {
  snprintf(s_info, sizeof(s_info), "%s", info);
  persist_write_string(PERSIST_INFO, s_info);
  if (s_info_layer) text_layer_set_text(s_info_layer, s_info);
}

void main_window_set_car_status(const char *status) {
  snprintf(s_car, sizeof(s_car), "%s", status);
  parse_car_status(s_car);
  update_car_layers();

  // Data arrived → show rows, stop spinner
  s_data_loaded = true;
  set_data_visible(true);
  spinner_stop();
}

void main_window_set_status(const char *text) {
  if (s_revert_timer) { app_timer_cancel(s_revert_timer); s_revert_timer = NULL; }
  snprintf(s_status, sizeof(s_status), "%s", text);
  if (s_status_layer) text_layer_set_text(s_status_layer, s_status);

  if (strcmp(text, "Refreshing...") == 0 || strcmp(text, "Connecting...") == 0) {
    // Loading state → show spinner, hide data
    s_data_loaded = false;
    set_data_visible(false);
    spinner_start();
  } else if (!s_data_loaded) {
    // Terminal state without data (login needed, etc.) → just stop spinner
    spinner_stop();
  }
}

void main_window_show_temp_status(const char *text) {
  if (s_revert_timer) app_timer_cancel(s_revert_timer);
  snprintf(s_status, sizeof(s_status), "%s", text);
  if (s_status_layer) text_layer_set_text(s_status_layer, s_status);
  s_revert_timer = app_timer_register(3000, revert_status, NULL);
}

// Window Handlers

static void on_select(ClickRecognizerRef ref, void *ctx) {
  commands_open_menu();
}

static void on_up(ClickRecognizerRef ref, void *ctx) {
  DictionaryIterator *iter;
  if (app_message_outbox_begin(&iter) == APP_MSG_OK) {
    dict_write_cstring(iter, MESSAGE_KEY_COMMAND, "refresh");
    app_message_outbox_send();
  }
  // Don't hide existing data on manual refresh, just show status
  if (s_revert_timer) { app_timer_cancel(s_revert_timer); s_revert_timer = NULL; }
  snprintf(s_status, sizeof(s_status), "Refreshing...");
  if (s_status_layer) text_layer_set_text(s_status_layer, s_status);
}

static void click_config(void *ctx) {
  window_single_click_subscribe(BUTTON_ID_SELECT, on_select);
  window_single_click_subscribe(BUTTON_ID_UP, on_up);
}

static void window_load(Window *w) {
  Layer *root = window_get_root_layer(w);
  GRect b = layer_get_bounds(root);
  window_set_background_color(w, GColorBlack);

  int margin = PBL_IF_ROUND_ELSE(28, 8);
  int width = b.size.w - 2 * margin;
  int header_h = PBL_IF_ROUND_ELSE(50, 44);
  int footer_h = PBL_IF_ROUND_ELSE(50, 50);

  // Separator layer
  s_separator_layer = layer_create(b);
  layer_set_update_proc(s_separator_layer, separator_draw);
  layer_add_child(root, s_separator_layer);

  // Car info (top)
  int info_y = PBL_IF_ROUND_ELSE(16, 6);
  s_info_layer =
      make_text(root, GRect(margin, info_y, width, 34), s_info,
                fonts_get_system_font(FONT_KEY_GOTHIC_28_BOLD), GTextAlignmentCenter, GColorWhite);

  // Data area
  int data_area_top = header_h + 4;
  int data_area_bottom = b.size.h - footer_h;
  int row_h = 24;
  int total_rows_h = 4 * row_h;
  int row_start = data_area_top + (data_area_bottom - data_area_top - total_rows_h) / 2;

  // Row 1: Engine
  s_engine_lbl = make_text(root, GRect(margin, row_start, width, row_h), "Engine",
                           fonts_get_system_font(FONT_KEY_GOTHIC_24), GTextAlignmentLeft,
                           PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite));
  s_engine_layer = make_text(root, GRect(margin, row_start, width, row_h), s_engine_str,
                             fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD), GTextAlignmentRight,
                             PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite));

  // Row 2: Doors
  s_lock_lbl = make_text(root, GRect(margin, row_start + row_h, width, row_h), "Doors",
                         fonts_get_system_font(FONT_KEY_GOTHIC_24), GTextAlignmentLeft,
                         PBL_IF_COLOR_ELSE(GColorMediumSpringGreen, GColorWhite));
  s_lock_layer = make_text(root, GRect(margin, row_start + row_h, width, row_h), s_doors,
                           fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD), GTextAlignmentRight,
                           PBL_IF_COLOR_ELSE(GColorMediumSpringGreen, GColorWhite));

  // Row 3: Windows
  s_windows_lbl = make_text(root, GRect(margin, row_start + 2 * row_h, width, row_h), "Windows",
                            fonts_get_system_font(FONT_KEY_GOTHIC_24), GTextAlignmentLeft,
                            PBL_IF_COLOR_ELSE(GColorMediumSpringGreen, GColorWhite));
  s_windows_layer = make_text(root, GRect(margin, row_start + 2 * row_h, width, row_h), s_windows,
                              fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD), GTextAlignmentRight,
                              PBL_IF_COLOR_ELSE(GColorMediumSpringGreen, GColorWhite));

  // Row 4: Fuel
  s_fuel_lbl = make_text(root, GRect(margin, row_start + 3 * row_h, width, row_h), "Fuel",
                         fonts_get_system_font(FONT_KEY_GOTHIC_24), GTextAlignmentLeft,
                         GColorWhite);
  s_fuel_layer = make_text(root, GRect(margin, row_start + 3 * row_h, width, row_h), s_fuel,
                           fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD), GTextAlignmentRight,
                           GColorWhite);

  // Spinner (centered in data area)
  int spinner_x = (b.size.w - SPINNER_SIZE) / 2;
  int spinner_y = data_area_top + (data_area_bottom - data_area_top - SPINNER_SIZE) / 2;
  s_spinner_layer = layer_create(GRect(spinner_x, spinner_y, SPINNER_SIZE, SPINNER_SIZE));
  layer_set_update_proc(s_spinner_layer, spinner_draw);
  layer_add_child(root, s_spinner_layer);

  // Status (footer)
  int status_y = b.size.h - footer_h + PBL_IF_ROUND_ELSE(4, 4);
  s_status_layer = make_text(root, GRect(margin, status_y, width, 28), s_status,
                             fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD), GTextAlignmentCenter,
                             GColorLightGray);

  // Initial state: spinner visible, data hidden
  s_data_loaded = false;
  set_data_visible(false);
  spinner_start();

  window_set_click_config_provider(w, click_config);
}

static void window_unload(Window *w) {
  spinner_stop();
  text_layer_destroy(s_info_layer);
  text_layer_destroy(s_engine_lbl);
  text_layer_destroy(s_engine_layer);
  text_layer_destroy(s_lock_lbl);
  text_layer_destroy(s_lock_layer);
  text_layer_destroy(s_windows_lbl);
  text_layer_destroy(s_windows_layer);
  text_layer_destroy(s_fuel_lbl);
  text_layer_destroy(s_fuel_layer);
  text_layer_destroy(s_status_layer);
  layer_destroy(s_separator_layer);
  layer_destroy(s_spinner_layer);
  if (s_revert_timer) app_timer_cancel(s_revert_timer);
}

void main_window_push(void) {
  load_persisted();
  s_window = window_create();
  window_set_window_handlers(s_window, (WindowHandlers){
                                           .load = window_load,
                                           .unload = window_unload,
                                       });
  window_stack_push(s_window, true);
}
