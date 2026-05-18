/* 24 V rail voltage-sense task.
 *
 * Reads V24_SENSE (GPIO1, ADC1_CH0) through the 100k/11k divider, every
 * 2 s. Provides a voltage-only SOC fallback for power_task in case BLE
 * is unreachable, and feeds the data into the ULP routine's calibration
 * table over time.
 *
 * THIS IS A STUB. Implementation TODO:
 *   1. ADC oneshot init on GPIO1 (ADC1_CH0), 12-bit, attenuation 11dB.
 *   2. Apply divider gain: V_actual = V_adc * (100k + 11k) / 11k =
 *      V_adc * 10.09.
 *   3. EMA-smooth the result (alpha 0.2, slower than the main current
 *      EMA since voltage is steadier).
 *   4. Expose latest smoothed voltage via a small read-only state
 *      module (or a second mailbox).
 */

#include "main.h"
#include "esp_log.h"

static const char *TAG = "adc_task";


void adc_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "starting — STUB; no ADC sampling yet");

    while (true) {
        /* TODO: adc_oneshot_read on GPIO1, divider math, EMA */
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}
