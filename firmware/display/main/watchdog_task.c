/* Watchdog / link-down detector.
 *
 * Watches g_frame_mailbox's last received_ms; if no fresh frame has
 * arrived in 90 s, emits a virtual event so render_task can draw a
 * "LINK DOWN — last reading at HH:MM" overlay (per state_machine.md
 * § "Display-side reactions").
 *
 * Escalates at 6 min ("MONITOR ASLEEP — pack < 15 %") and 30 min
 * ("MONITOR ASLEEP — pack < 10 %", red banner) per design.
 *
 * THIS IS A STUB. Implementation TODO:
 *   1. Run a 10 s timer; on each tick read latest received_ms, compare
 *      to esp_timer_get_time() / 1000.
 *   2. On boundary crossings, push a synthetic frame to g_frame_mailbox
 *      with a flags field that render_task interprets as "show overlay".
 *      (Or a separate channel — TBD; cleaner is a dedicated mailbox.)
 */

#include "main.h"
#include "esp_log.h"

static const char *TAG = "watchdog_task";


void watchdog_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "starting — STUB; no link-down detection yet");

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}
