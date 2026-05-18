/* Battery-side firmware entry point.
 *
 * Creates the four FreeRTOS tasks specified in
 * docs/firmware/architecture.md § "Battery-side tasks (FreeRTOS)" and
 * hands off. Application logic lives in the *_task.c files.
 *
 * Stack and priorities are minimal-defensible; tune via `idf.py
 * menuconfig` once we have real workload measurements.
 */

#include "main.h"

#include "esp_log.h"
#include "nvs_flash.h"

static const char *TAG = "volthium-bms-link";

QueueHandle_t g_reading_mailbox = NULL;
volthium_estimator_t g_estimator = {0};


static void init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS needs erasing; reformatting");
        nvs_flash_erase();
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
}


void app_main(void)
{
    ESP_LOGI(TAG, "volthium battery-side firmware starting");

    /* NVS first — we use it for estimator state persistence and the
     * voltage-SOC table the ULP routine reads. */
    init_nvs();

    /* Initialize the estimator with our defaults + hybrid mode on (see
     * docs/hardware/bms_calibration.md for why hybrid wins). */
    volthium_estimator_config_t cfg = VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT;
    cfg.use_hybrid = true;
    cfg.capacity_ah = 215.0f;   /* observed per-battery capacity from real data */
    volthium_estimator_init(&g_estimator, &cfg);

    /* One-slot mailbox for the fused sample. */
    g_reading_mailbox = xQueueCreate(1, sizeof(fused_reading_t));
    configASSERT(g_reading_mailbox != NULL);

    /* Spin up the workers.  Priorities and stack sizes per
     * architecture.md table — refine after profiling. */
    xTaskCreatePinnedToCore(power_task, "power_task", 4096, NULL, 6, NULL, /*core=*/0);
    xTaskCreatePinnedToCore(adc_task,   "adc_task",   2048, NULL, 3, NULL, /*core=*/0);
    xTaskCreatePinnedToCore(ble_task,   "ble_task",   8192, NULL, 5, NULL, /*core=*/0);
    xTaskCreatePinnedToCore(tx_task,    "tx_task",    4096, NULL, 4, NULL, /*core=*/1);

    ESP_LOGI(TAG, "all tasks created; app_main returning");
    /* app_main returns; FreeRTOS continues running tasks. */
}
