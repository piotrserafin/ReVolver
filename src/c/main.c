#include <pebble.h>

#include "modules/messaging.h"
#include "modules/quick_launch.h"
#include "windows/main_window.h"

static void init(void) {
  messaging_init();
  main_window_push();
  quick_launch_init();
}

int main(void) {
  init();
  app_event_loop();
}
