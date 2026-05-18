/* E-paper render task.
 *
 * Pulls the latest decoded frame from g_frame_mailbox, formats the
 * dashboard screen, and pushes pixels to the 4.2" tri-color Waveshare
 * panel via SPI (GPIO5..10 per docs/hardware/schematic_display_side.md).
 *
 * Refresh strategy:
 *   - Full refresh on boot, on BTN_REFRESH, and every 10 min to clear
 *     e-paper ghosting.
 *   - Partial refresh otherwise — only the headline number (time
 *     remaining or SOC %) plus the small per-battery stats. Header
 *     stays static between full refreshes.
 *
 * THIS IS A STUB. Implementation TODO:
 *   1. SPI master init on host 2 (HSPI), 4 MHz nominal, half-duplex.
 *   2. GPIO config for CS / DC / RST / BUSY per schematic.
 *   3. Waveshare 4.2" tri-color driver — there's a public ESP-IDF
 *      component (`waveshare_epd` or roll our own from
 *      `firmware/display/components/epd_4in2b_v2/` per architecture.md).
 *   4. Two frame buffers (black layer + red layer), drawing via a
 *      minimal text/box renderer.
 *   5. On BTN_NEXT, cycle to alternate screens (cell voltages, history
 *      sparkline, temperature, cycle counts).
 *   6. On BTN_RELEASE_BLE, draw a 5-min countdown overlay; clear when
 *      the countdown ends or the user presses BTN_REFRESH.
 */

#include "main.h"
#include "esp_log.h"

static const char *TAG = "render_task";


void render_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "starting — STUB; no SPI / e-paper work yet");

    rx_frame_t r;
    while (true) {
        /* Wait for new data or a button event. xQueuePeek with timeout
         * suffices for now; real impl would also xQueueReceive on
         * g_button_events. */
        if (xQueuePeek(g_frame_mailbox, &r, pdMS_TO_TICKS(5000)) == pdTRUE) {
            ESP_LOGI(TAG, "would render: state=%u SOC=%u/%u min_left=%u",
                     r.body.state, r.body.soc_a_pct, r.body.soc_b_pct,
                     r.body.minutes_remaining);
        }
    }
}
