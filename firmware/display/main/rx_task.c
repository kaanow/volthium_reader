/* RS-485 frame receiver task.
 *
 * Reads bytes off UART1 (GPIO17/18 per docs/hardware/schematic_display_side.md),
 * scans for the 0xAA 0x55 magic, attempts to decode each 43-byte frame
 * via volthium_decode(). On success, posts to g_frame_mailbox.
 *
 * Also handles outgoing "release BLE" messages triggered by the
 * BTN_RELEASE_BLE button event — flips DE high, writes a one-byte
 * command (or a small structured frame; TBD; pending firmware spec
 * for the back-channel), flips DE low.
 *
 * THIS IS A STUB. Implementation TODO:
 *   1. uart_driver_install on UART1, 9600 8N1, with RX ring buffer >=
 *      2 * VOLTHIUM_FRAME_SIZE so we never lose a frame.
 *   2. Loop: read bytes until 0xAA 0x55 seen, then read 41 more, then
 *      pass the 43-byte buffer to volthium_decode(). On any error,
 *      drop the buffer and re-scan.
 *   3. On success: build rx_frame_t (body + esp_timer ms), xQueueOverwrite.
 *   4. Subscribe to g_button_events for BTN_RELEASE_BLE; on that
 *      event, drive GPIO2 (DE/RE) high, send back-channel message,
 *      drive low.
 */

#include "main.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "rx_task";


void rx_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "starting — STUB; no UART work yet");

    /* TODO: replace with real UART-driven loop. For now, fake a frame
     * once every 30 s so render_task has something to draw. */
    rx_frame_t fake = {
        .body = {
            .version = VOLTHIUM_VERSION,
            .seq = 0,
            .state = VOLTHIUM_STATE_DISCHARGING,
            .pack_voltage_cV = 2649,
            .pack_current_cA = -450,
            .pack_power_W = -119,
            .soc_a_pct = 93, .soc_b_pct = 93,
            .v_a_mV = 13245, .v_b_mV = 13247,
            .i_a_cA = -225, .i_b_cA = -225,
            .temp_a_C = 22, .temp_b_C = 22,
            .remaining_ah_a_dAh = 2010, .remaining_ah_b_dAh = 1980,
            .delta_v_a_mV = 8, .delta_v_b_mV = 9,
            .minutes_remaining = 2180,
            .flags = VOLTHIUM_FLAG_CHARGING_FETS | VOLTHIUM_FLAG_DISCHARGING_FETS,
        },
    };

    TickType_t last_wake = xTaskGetTickCount();
    while (true) {
        fake.body.seq++;
        fake.received_ms = (uint64_t)(esp_timer_get_time() / 1000);
        xQueueOverwrite(g_frame_mailbox, &fake);
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(30000));
    }
}
