#include "quick_launch.h"

#include "../windows/main_window.h"
#include "messaging.h"

#define QL_ACTION_MAX 32
#define QL_RETRY_MS 500
#define QL_JS_TIMEOUT_MS 10000
#define QL_RESULT_TIMEOUT_MS 60000  // XHRs have no timeout; don't block status updates forever
#define QL_DONE_MS 3000             // matches the temp status display time

typedef enum { QL_IDLE, QL_ARMED, QL_SENT, QL_DONE } QlState;

static QlState s_state = QL_IDLE;
static char s_action[QL_ACTION_MAX];
static bool s_exit;
static bool s_js_ready;
static AppTimer *s_timer;
static uint32_t s_waited_ms;

static void set_timer(uint32_t ms, AppTimerCallback cb) {
  if (s_timer)
    app_timer_cancel(s_timer);
  s_timer = app_timer_register(ms, cb, NULL);
}

static bool action_allowed(const char *cmd) {
  // Unlock is never a quick action: a stray button press must not open the car.
  return cmd[0] && strcmp(cmd, "none") != 0 && strncmp(cmd, "unlock", 6) != 0;
}

static void on_done(void *ctx) {
  s_timer = NULL;
  s_state = QL_IDLE;
  if (s_exit)
    window_stack_pop_all(true);
}

static void on_result_timeout(void *ctx) {
  s_timer = NULL;
  s_state = QL_IDLE;
}

static void try_send(void *ctx) {
  s_timer = NULL;
  if (s_state != QL_ARMED)
    return;

  if (s_js_ready && messaging_send_command(s_action)) {
    s_state = QL_SENT;
    main_window_set_status("Sending...");
    set_timer(QL_RESULT_TIMEOUT_MS, on_result_timeout);
    return;
  }

  s_waited_ms += QL_RETRY_MS;
  if (s_waited_ms >= QL_JS_TIMEOUT_MS) {
    s_state = QL_IDLE;
    main_window_show_temp_status("Phone not ready");
    messaging_vibrate(false);
    return;
  }
  set_timer(QL_RETRY_MS, try_send);
}

// Public API

void quick_launch_set_action(const char *cmd) {
  snprintf(s_action, sizeof(s_action), "%s", cmd);
  persist_write_string(MESSAGE_KEY_QUICK_ACTION, s_action);
}

void quick_launch_set_exit(bool exit) {
  s_exit = exit;
  persist_write_bool(MESSAGE_KEY_QUICK_EXIT, exit);
}

void quick_launch_init(void) {
  if (persist_exists(MESSAGE_KEY_QUICK_EXIT))
    s_exit = persist_read_bool(MESSAGE_KEY_QUICK_EXIT);
  if (persist_exists(MESSAGE_KEY_QUICK_ACTION))
    persist_read_string(MESSAGE_KEY_QUICK_ACTION, s_action, sizeof(s_action));

  if (launch_reason() != APP_LAUNCH_QUICK_LAUNCH || !action_allowed(s_action))
    return;

  s_state = QL_ARMED;
  s_waited_ms = 0;
  main_window_set_status("Quick action...");
  set_timer(QL_RETRY_MS, try_send);
}

void quick_launch_on_js_ready(void) {
  if (s_js_ready)
    return;
  s_js_ready = true;
  if (s_state == QL_ARMED) {
    if (s_timer)
      app_timer_cancel(s_timer);
    try_send(NULL);
  }
}

void quick_launch_on_result(void) {
  if (s_state != QL_SENT)
    return;
  s_state = QL_DONE;
  set_timer(QL_DONE_MS, on_done);
}

bool quick_launch_is_busy(void) {
  return s_state != QL_IDLE;
}
