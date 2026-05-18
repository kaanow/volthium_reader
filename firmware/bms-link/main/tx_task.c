/* RS-485 frame transmitter task.
 *
 * Pulls the latest fused reading from the mailbox, runs the estimator,
 * builds a volthium wire-protocol frame (firmware/common/volthium_lib/
 * wire_protocol.h), and clocks it out the half-duplex RS-485
 * transceiver.
 *
 * THIS IS A STUB. Implementation TODO:
 *   1. uart_driver_install on UART1 (TX=GPIO17, RX=GPIO18 per
 *      docs/hardware/schematic_battery_side.md), 9600 8N1.
 *   2. GPIO2 = DE/RE (drive-enable). Set high before transmit, return
 *      low afterward so the receiver can listen for the display-side
 *      "release BLE" broadcast.
 *   3. On each cycle:
 *        - xQueuePeek mailbox
 *        - run g_estimator.update()
 *        - assemble volthium_body_t + volthium_encode()
 *        - assert DE, uart_write_bytes, wait for tx complete, deassert
 *   4. Cycle period from power_task's view: NORMAL=30s, LOW=60s,
 *      DEEP_SLEEP=task suspended.
 */

#include "main.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "tx_task";

static uint8_t g_seq = 0;


static void send_one_frame(const fused_reading_t *r, const volthium_estimate_t *est)
{
    volthium_body_t body = {
        .version          = VOLTHIUM_VERSION,
        .seq              = g_seq++,
        .uptime_ms        = (uint32_t)(esp_timer_get_time() / 1000),
        .state            = (uint8_t)est->state,
        .pack_voltage_cV  = r->pack.has_pack_current
                            ? (uint16_t)(r->v_a_mV + r->v_b_mV) / 10
                            : VOLTHIUM_SENTINEL_U16,
        .pack_current_cA  = r->pack.has_pack_current
                            ? (int16_t)(r->pack.pack_current_a * 100.0f)
                            : VOLTHIUM_SENTINEL_I16,
        .pack_power_W     = r->pack.has_pack_power
                            ? (int16_t)r->pack.pack_power_w
                            : VOLTHIUM_SENTINEL_I16,
        .soc_a_pct        = r->pack.has_max_soc ? (uint8_t)r->pack.max_soc_pct : VOLTHIUM_SENTINEL_U8,
        .soc_b_pct        = r->pack.has_min_soc ? (uint8_t)r->pack.min_soc_pct : VOLTHIUM_SENTINEL_U8,
        .v_a_mV           = r->v_a_mV,
        .v_b_mV           = r->v_b_mV,
        .i_a_cA           = r->i_a_cA,
        .i_b_cA           = r->i_b_cA,
        .temp_a_C         = r->temp_a_c,
        .temp_b_C         = r->temp_b_c,
        .remaining_ah_a_dAh = r->rem_a_dAh,
        .remaining_ah_b_dAh = r->rem_b_dAh,
        .delta_v_a_mV     = r->delta_v_a_mV,
        .delta_v_b_mV     = r->delta_v_b_mV,
        .minutes_remaining = est->has_minutes_remaining
                            ? (uint16_t)est->minutes_remaining
                            : VOLTHIUM_SENTINEL_U16,
        .flags            = r->flags,
        .reserved         = 0,
    };

    uint8_t frame[VOLTHIUM_FRAME_SIZE];
    size_t n = volthium_encode(&body, frame, sizeof(frame));
    if (n != VOLTHIUM_FRAME_SIZE) {
        ESP_LOGE(TAG, "encode failed");
        return;
    }

    /* TODO: real UART write with DE handling */
    ESP_LOGI(TAG, "frame seq=%u state=%u min=%u (TX stub — not actually sent)",
             body.seq, body.state, body.minutes_remaining);
}


void tx_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "starting — STUB; logs frames to console instead of UART");

    fused_reading_t r;
    TickType_t last_wake = xTaskGetTickCount();
    while (true) {
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(30000));
        if (xQueuePeek(g_reading_mailbox, &r, 0) == pdTRUE && r.valid) {
            volthium_estimate_t est = volthium_estimator_update(&g_estimator, &r.pack);
            send_one_frame(&r, &est);
        }
    }
}
