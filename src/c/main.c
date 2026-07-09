#include <pebble.h>

#include "modules/messaging.h"
#include "windows/main_window.h"

static void init(void) {
  messaging_init();
  main_window_push();
}

int main(void) {
  init();
  app_event_loop();
}
