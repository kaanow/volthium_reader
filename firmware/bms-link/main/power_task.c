/* Power-tier state machine.
 *
 * Watches SOC and shifts the system between NORMAL / LOW / DEEP_SLEEP /
 * HARD_CUT per docs/firmware/state_machine.md, with hysteresis (fast
 * down, slow up). Drives the P-MOSFET load-switch (GPIO4) and the BLE
 * task's connection state.
 *
 * THIS IS A STUB. Implementation TODO:
 *   1. Implement the 4-state machine with hysteresis (5 s instant down,
 *      2 min sustained up).
 *   2. Wire GPIO4 → MOSFET enable. HIGH = downstream rail disabled
 *      (hard-cut), LOW = enabled.
 *   3. On entry to DEEP_SLEEP: signal ble_task to disconnect; arm ULP
 *      voltage-monitor routine; esp_deep_sleep_enable_timer_wakeup(10
 *      minutes) + GPIO wakeup (override button on GPIO7).
 *   4. On entry to HARD_CUT: drive GPIO4 high, then deep-sleep; only
 *      the ULP voltage routine wakes us, every 60 s.
 *   5. On wake from ULP: read V24_SENSE via ADC1_CH0 (GPIO1), look up
 *      SOC via the voltage_soc_table.csv-derived NVS table, decide
 *      next state.
 *   6. Persist state + hysteresis-counter in NVS so reboots don't lose
 *      it.
 */

#include "main.h"
#include "esp_log.h"

static const char *TAG = "power_task";


void power_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "starting — STUB; no state-machine work yet");

    while (true) {
        /* TODO: read latest sample, run state machine, drive MOSFET */
        vTaskDelay(pdMS_TO_TICKS(5000));
    }
}
