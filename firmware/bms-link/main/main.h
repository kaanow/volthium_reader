/* Battery-side firmware — shared task entry points + interop structs.
 *
 * Each task lives in its own translation unit (ble_task.c, tx_task.c,
 * etc.) and exposes one entry-point function declared here. main.c
 * creates the FreeRTOS tasks at startup. */

#ifndef VOLTHIUM_MAIN_H
#define VOLTHIUM_MAIN_H

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "volthium_lib/estimator.h"
#include "volthium_lib/wire_protocol.h"

/* The latest fused sample produced by ble_task.  Updated atomically via
 * a one-slot mailbox; readers (tx_task, adc_task, power_task) peek it
 * non-destructively. */
typedef struct {
    volthium_sample_t pack;       /* from ble_task → tx_task / power_task */
    /* per-battery raw fields the tx_task needs to fill the wire frame */
    int8_t   temp_a_c, temp_b_c;
    uint16_t v_a_mV, v_b_mV;
    int16_t  i_a_cA, i_b_cA;
    uint16_t rem_a_dAh, rem_b_dAh;
    uint16_t delta_v_a_mV, delta_v_b_mV;
    uint8_t  flags;
    bool     valid;
} fused_reading_t;

/* Globally accessible mailbox of one (FreeRTOS queue with depth 1). */
extern QueueHandle_t g_reading_mailbox;

/* The estimator instance — only mutated by ble_task / power_task,
 * read by tx_task. */
extern volthium_estimator_t g_estimator;

/* Task entry points — call via xTaskCreatePinnedToCore in main.c. */
void ble_task(void *arg);
void tx_task(void *arg);
void power_task(void *arg);
void adc_task(void *arg);

#endif
