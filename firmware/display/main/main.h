/* Display-side firmware — shared structs + task entry points. */

#ifndef VOLTHIUM_DISPLAY_MAIN_H
#define VOLTHIUM_DISPLAY_MAIN_H

#include <stdbool.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "volthium_lib/wire_protocol.h"

/* Latest decoded frame from rx_task → render_task / watchdog. */
extern QueueHandle_t g_frame_mailbox;
typedef struct {
    volthium_body_t body;       /* the wire fields */
    uint64_t        received_ms;/* esp_timer_get_time() / 1000 at decode */
} rx_frame_t;

/* Button events (debounced) → render_task + rx_task (for release-BLE). */
extern QueueHandle_t g_button_events;
typedef enum {
    BTN_REFRESH = 0,       /* full e-paper refresh */
    BTN_NEXT,              /* cycle info screens */
    BTN_RELEASE_BLE,       /* ask battery-side to release for 5 min */
} button_event_t;

/* Task entry points. */
void rx_task(void *arg);
void render_task(void *arg);
void input_task(void *arg);
void watchdog_task(void *arg);

#endif
