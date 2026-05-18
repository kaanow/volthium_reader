/* Display-side firmware entry point.
 *
 * Spawns the 4 tasks specified in docs/firmware/architecture.md
 * § "Display-side tasks". No BLE, no MOSFET, no ULP — the display
 * receives RS-485 frames and pushes them to the e-paper.
 */

#include "main.h"

#include "esp_log.h"
#include "nvs_flash.h"

static const char *TAG = "volthium-display";

QueueHandle_t g_frame_mailbox = NULL;
QueueHandle_t g_button_events = NULL;


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
    ESP_LOGI(TAG, "volthium display firmware starting");

    init_nvs();

    /* One-slot mailbox for the latest frame. xQueueOverwrite from
     * rx_task; xQueuePeek from the others. */
    g_frame_mailbox = xQueueCreate(1, sizeof(rx_frame_t));
    configASSERT(g_frame_mailbox != NULL);

    /* Small queue for debounced button events. */
    g_button_events = xQueueCreate(8, sizeof(button_event_t));
    configASSERT(g_button_events != NULL);

    /* Tasks. Priorities + stacks per architecture.md table — refine
     * once we have real workload data. */
    xTaskCreatePinnedToCore(rx_task,        "rx_task",       4096, NULL, 5, NULL, /*core=*/0);
    xTaskCreatePinnedToCore(render_task,    "render_task",   8192, NULL, 4, NULL, /*core=*/1);
    xTaskCreatePinnedToCore(input_task,     "input_task",    2048, NULL, 3, NULL, /*core=*/0);
    xTaskCreatePinnedToCore(watchdog_task,  "watchdog_task", 2048, NULL, 2, NULL, /*core=*/0);

    ESP_LOGI(TAG, "all tasks created; app_main returning");
}
