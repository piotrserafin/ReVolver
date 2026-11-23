#include "find_window.h"

#include "../modules/messaging.h"

// FIND_CAR wire format: "distance|bearing|note" (bearing -1 = none) or "!message".
#define FIND_SEP '|'
#define FIND_MSG_PREFIX '!'

static Window *s_window;
static TextLayer *s_title_layer;
static TextLayer *s_dir_layer;
static TextLayer *s_dist_layer;
static TextLayer *s_note_layer;
static TextLayer *s_msg_layer;  // status/error text, shown instead of the data rows

static char s_dir[4];
static char s_dist[16];
static char s_note[32];
static char s_msg[64];
static int s_bearing = -1;  // degrees clockwise from north to the car, -1 = none

// SELECT: how to get walking directions on the phone. The watch can't open anything on the
// phone (Pebble.openURL only works from the settings page), so it tells you where to tap.
#define FIND_HINT_MS 6000
static const char *FIND_HINT = "On your phone:\nReVolver settings\n> Walk to car";
static AppTimer *s_hint_timer;  // non-NULL while the hint is shown

#if defined(PBL_COMPASS)
// Arrow pointing at the car: bearing relative to where the top of the watch faces.
// Uses magnetic north (declination ignored: a few degrees in Europe).
#define FIND_HEADING_FILTER_DEG 5

static Layer *s_arrow_layer;
static GPath *s_arrow_path;
static CompassHeadingData s_heading;

static const GPathInfo ARROW_PATH_INFO = {
    .num_points = 7,
    .points = (GPoint[]){{0, -22}, {16, -4}, {6, -4}, {6, 22}, {-6, 22}, {-6, -4}, {-16, -4}},
};

static bool compass_usable(void) {
  return s_heading.compass_status == CompassStatusCalibrating ||
         s_heading.compass_status == CompassStatusCalibrated;
}

static bool show_arrow(void) {
  return s_msg[0] == '\0' && s_bearing >= 0 && compass_usable();
}

static void arrow_draw(Layer *layer, GContext *ctx) {
  if (!show_arrow())
    return;
  // magnetic_heading grows counter-clockwise, GPath rotation clockwise:
  // relative = bearing - (TRIG_MAX_ANGLE - magnetic_heading)
  int32_t angle = DEG_TO_TRIGANGLE(s_bearing) + s_heading.magnetic_heading;
  GRect b = layer_get_bounds(layer);
  gpath_rotate_to(s_arrow_path, angle % TRIG_MAX_ANGLE);
  gpath_move_to(s_arrow_path, grect_center_point(&b));
  graphics_context_set_fill_color(ctx, PBL_IF_COLOR_ELSE(GColorMediumSpringGreen, GColorWhite));
  gpath_draw_filled(ctx, s_arrow_path);
}

static void refresh_layers(void);

static void on_heading(CompassHeadingData data) {
  s_heading = data;
  refresh_layers();
}
#endif

static const char *direction_for(int deg) {
  static const char *DIRS[] = {"N", "NE", "E", "SE", "S", "SW", "W", "NW"};
  return DIRS[((deg % 360 + 360) % 360 + 22) / 45 % 8];
}

static void refresh_layers(void) {
  if (!s_window)
    return;
  bool hint = s_hint_timer != NULL;
  bool msg = hint || s_msg[0] != '\0';
  bool arrow = false;
  const char *note = s_note;
#if defined(PBL_COMPASS)
  arrow = !hint && show_arrow();
  if (!msg && s_bearing >= 0 && s_heading.compass_status == CompassStatusDataInvalid)
    note = "Move your wrist";  // compass calibrating; direction text meanwhile
  layer_set_hidden(s_arrow_layer, !arrow);
  layer_mark_dirty(s_arrow_layer);
#endif
  text_layer_set_text(s_dir_layer, s_dir);
  text_layer_set_text(s_dist_layer, s_dist);
  text_layer_set_text(s_note_layer, note);
  text_layer_set_text(s_msg_layer, hint ? FIND_HINT : s_msg);
  text_layer_set_font(s_msg_layer,
                      fonts_get_system_font(hint ? FONT_KEY_GOTHIC_18_BOLD : FONT_KEY_GOTHIC_24_BOLD));
  layer_set_hidden(text_layer_get_layer(s_dir_layer), msg || arrow);
  layer_set_hidden(text_layer_get_layer(s_dist_layer), msg);
  layer_set_hidden(text_layer_get_layer(s_note_layer), msg);
  layer_set_hidden(text_layer_get_layer(s_msg_layer), !msg);
}

static TextLayer *make_text(Layer *root, GRect frame, const char *font_key, GColor color) {
  TextLayer *t = text_layer_create(frame);
  text_layer_set_background_color(t, GColorClear);
  text_layer_set_text_color(t, color);
  text_layer_set_font(t, fonts_get_system_font(font_key));
  text_layer_set_text_alignment(t, GTextAlignmentCenter);
  text_layer_set_overflow_mode(t, GTextOverflowModeWordWrap);
  layer_add_child(root, text_layer_get_layer(t));
  return t;
}

static void hint_done(void *ctx) {
  s_hint_timer = NULL;
  refresh_layers();
}

static void on_select(ClickRecognizerRef ref, void *ctx) {
  if (s_hint_timer)
    app_timer_cancel(s_hint_timer);
  s_hint_timer = app_timer_register(FIND_HINT_MS, hint_done, NULL);
  refresh_layers();
  messaging_send_command("find:phone");  // phone shows the same hint as a toast
}

static void click_config(void *ctx) {
  window_single_click_subscribe(BUTTON_ID_SELECT, on_select);
}

static void window_load(Window *w) {
  Layer *root = window_get_root_layer(w);
  GRect b = layer_get_bounds(root);
  window_set_background_color(w, GColorBlack);

  int margin = PBL_IF_ROUND_ELSE(24, 6);
  int width = b.size.w - 2 * margin;
  // Content block (title, direction, distance, note) is ~140 px; center it vertically
  // so tall screens (emery 228, gabbro 260) don't leave the bottom half empty.
  int top = (b.size.h - 140) / 2;
  if (top < 6)
    top = 6;

  s_title_layer = make_text(root, GRect(margin, top, width, 30), FONT_KEY_GOTHIC_24_BOLD,
                            PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite));
  text_layer_set_text(s_title_layer, "Find car");

  s_dir_layer = make_text(root, GRect(margin, top + 30, width, 50), FONT_KEY_BITHAM_42_BOLD,
                          PBL_IF_COLOR_ELSE(GColorMediumSpringGreen, GColorWhite));
  s_dist_layer =
      make_text(root, GRect(margin, top + 82, width, 34), FONT_KEY_GOTHIC_28_BOLD, GColorWhite);
  s_note_layer = make_text(root, GRect(margin, top + 116, width, 24), FONT_KEY_GOTHIC_18,
                           PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite));
  s_msg_layer = make_text(root, GRect(margin, top + 44, width, 90), FONT_KEY_GOTHIC_24_BOLD,
                          GColorWhite);
#if defined(PBL_COMPASS)
  s_arrow_layer = layer_create(GRect(margin, top + 30, width, 50));
  layer_set_update_proc(s_arrow_layer, arrow_draw);
  layer_add_child(root, s_arrow_layer);
  s_arrow_path = gpath_create(&ARROW_PATH_INFO);
  // Until the first heading event: invalid → direction text.
  s_heading = (CompassHeadingData){.compass_status = CompassStatusDataInvalid};
  // No compass_service_peek(): without a subscription it subscribes by itself, and the
  // second subscribe below would register the same event entry twice (firmware crash later).
  // Subscribe resets the config, so the filter goes after it.
  compass_service_subscribe(on_heading);
  compass_service_set_heading_filter(DEG_TO_TRIGANGLE(FIND_HEADING_FILTER_DEG));
#endif
  window_set_click_config_provider(w, click_config);
  refresh_layers();
}

static void window_unload(Window *w) {
  messaging_send_command("find:stop");
  if (s_hint_timer) {
    app_timer_cancel(s_hint_timer);
    s_hint_timer = NULL;
  }
#if defined(PBL_COMPASS)
  compass_service_unsubscribe();
  gpath_destroy(s_arrow_path);
  layer_destroy(s_arrow_layer);
#endif
  text_layer_destroy(s_title_layer);
  text_layer_destroy(s_dir_layer);
  text_layer_destroy(s_dist_layer);
  text_layer_destroy(s_note_layer);
  text_layer_destroy(s_msg_layer);
  window_destroy(s_window);
  s_window = NULL;
}

// Public API

void find_window_set_data(const char *raw) {
  if (raw[0] == FIND_MSG_PREFIX) {
    snprintf(s_msg, sizeof(s_msg), "%s", raw + 1);
    refresh_layers();
    return;
  }

  char buf[96];
  snprintf(buf, sizeof(buf), "%s", raw);
  char *bearing = strchr(buf, FIND_SEP);
  char *note = bearing ? strchr(bearing + 1, FIND_SEP) : NULL;
  if (!note)
    return;
  *bearing++ = '\0';
  *note++ = '\0';

  int deg = atoi(bearing);
  s_bearing = deg < 0 ? -1 : deg % 360;
  snprintf(s_dir, sizeof(s_dir), "%s", deg < 0 ? "" : direction_for(deg));
  snprintf(s_dist, sizeof(s_dist), "%.*s", (int)sizeof(s_dist) - 1, buf);
  snprintf(s_note, sizeof(s_note), "%.*s", (int)sizeof(s_note) - 1, note);
  s_msg[0] = '\0';
  refresh_layers();
}

void find_window_push(void) {
  if (s_window)
    return;
  s_dir[0] = '\0';
  s_dist[0] = '\0';
  s_note[0] = '\0';
  s_bearing = -1;
  snprintf(s_msg, sizeof(s_msg), "Locating car...");

  s_window = window_create();
  window_set_window_handlers(s_window, (WindowHandlers){
                                           .load = window_load,
                                           .unload = window_unload,
                                       });
  window_stack_push(s_window, true);
  messaging_send_command("find:start");
}
