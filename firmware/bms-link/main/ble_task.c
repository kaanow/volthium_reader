/* BLE central task — holds persistent connections to both Volthium
 * BMSes, queries them on a cycle, fuses into a PackReading, posts to
 * the mailbox.
 *
 * THIS IS A STUB. Implementation TODO:
 *   1. NimBLE init + scan + filter by advertised name pattern
 *      "V-12V???Ah-*" (see volthium/pack.py for the regex).
 *   2. Connect to each match; discover the Nordic UART service
 *      (6e400001-b5a3-f393-e0a9-e50e24dcca9e); subscribe to the RX
 *      characteristic.
 *   3. Send the EJ BMS command frame `:000250000E03~` on TX, accumulate
 *      notification bytes on RX, validate per docs/firmware/architecture.md
 *      § "RS-485 framing" + the parent EJ protocol decoder.
 *   4. Parse the response into a per-battery sample. The parser code
 *      lives in firmware/common/volthium_lib/bms_decoder.{h,c} —
 *      pending (see Task #N in docs/STATUS.md).
 *   5. Combine the two batteries' samples into a fused_reading_t, post
 *      to g_reading_mailbox via xQueueOverwrite (so older samples are
 *      replaced atomically).
 *   6. Handle flaps per docs/firmware/ble_flap_recovery.md (single
 *      missed read is normal; backoff escalation after 5+ failures).
 */

#include "main.h"
#include "esp_log.h"

static const char *TAG = "ble_task";


void ble_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "starting — STUB; no BLE work yet");

    /* TODO: replace this with the real loop.  For now, post a synthetic
     * sample every 30 s so the rest of the system has something to
     * exercise. */
    fused_reading_t fake = {
        .pack = {
            .has_pack_current = true,  .pack_current_a = -3.5f,
            .has_pack_power   = true,  .pack_power_w   = -90.0f,
            .has_max_soc      = true,  .max_soc_pct    = 87.0f,
            .has_min_soc      = true,  .min_soc_pct    = 86.0f,
            .has_remaining_ah = true,  .remaining_ah_avg = 184.0f,
        },
        .temp_a_c = 22, .temp_b_c = 22,
        .v_a_mV = 13200, .v_b_mV = 13200,
        .i_a_cA = -175, .i_b_cA = -175,
        .rem_a_dAh = 1850, .rem_b_dAh = 1830,
        .delta_v_a_mV = 8, .delta_v_b_mV = 9,
        .flags = VOLTHIUM_FLAG_CHARGING_FETS | VOLTHIUM_FLAG_DISCHARGING_FETS,
        .valid = true,
    };

    TickType_t last_wake = xTaskGetTickCount();
    uint64_t ts_ms = 0;
    while (true) {
        fake.pack.ts_ms = ts_ms;
        xQueueOverwrite(g_reading_mailbox, &fake);
        ts_ms += 30000;
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(30000));
    }
}
