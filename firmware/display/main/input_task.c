/* Button input task.
 *
 * Reads GPIO12/13/14 (REFRESH / NEXT / RELEASE_BLE — see
 * docs/hardware/schematic_display_side.md), debounces with a 50 ms
 * filter, and posts events to g_button_events.
 *
 * Long-press logic (≥2 s) per docs/firmware/state_machine.md table
 * "Button function map" — e.g. long-press BTN_REFRESH = forced full
 * refresh.
 *
 * THIS IS A STUB. Implementation TODO:
 *   1. GPIO config: inputs with pull-up enabled on 12/13/14.
 *   2. Interrupt-on-change → ISR queues a raw edge event to a
 *      task-internal queue.
 *   3. Task wakes, applies debounce (sample again 50 ms later, confirm
 *      still pressed), measures press duration on release.
 *   4. Map (button, duration) → button_event_t, post to
 *      g_button_events.
 *   5. Hold the BOOT-strap pins clear of any input that might
 *      interfere — all three buttons are post-boot so this is safe.
 */

#include "main.h"
#include "esp_log.h"

static const char *TAG = "input_task";


void input_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "starting — STUB; no GPIO input yet");

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
