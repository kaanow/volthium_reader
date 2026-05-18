/* Standalone test for the C wire-protocol port.
 *
 * Build:
 *     cc -std=c11 -Wall -Wextra -Werror -o test_wire_protocol \
 *        test_wire_protocol.c wire_protocol.c
 *
 * Run:
 *     ./test_wire_protocol
 *
 * Expected output: PASS lines for every test, then "all tests passed".
 *
 * The Python side has the same vectors in
 * tests/test_wire_protocol.py — both sides must agree.
 */

#include "wire_protocol.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static int g_fail = 0;

#define EXPECT(cond, label) do {                          \
    if (cond) {                                            \
        printf("  PASS  %s\n", label);                     \
    } else {                                               \
        printf("  FAIL  %s  (line %d)\n", label, __LINE__);\
        g_fail++;                                          \
    }                                                      \
} while (0)


static void test_crc_known_vector(void)
{
    const uint8_t data[] = { '1','2','3','4','5','6','7','8','9' };
    uint16_t crc = volthium_crc16_ccitt(data, sizeof(data));
    EXPECT(crc == 0x29B1, "CRC-16/CCITT-FALSE('123456789') == 0x29B1");
}

static void test_crc_empty(void)
{
    uint16_t crc = volthium_crc16_ccitt((const uint8_t *)"", 0);
    EXPECT(crc == 0xFFFF, "CRC-16/CCITT-FALSE('') == 0xFFFF");
}

static void test_frame_size(void)
{
    EXPECT(sizeof(volthium_frame_t) == 43, "sizeof(volthium_frame_t) == 43");
    EXPECT(sizeof(volthium_body_t) == 39, "sizeof(volthium_body_t) == 39");
}

static void test_encode_decode_roundtrip(void)
{
    volthium_body_t body = {
        .version          = VOLTHIUM_VERSION,
        .seq              = 42,
        .uptime_ms        = 12345,
        .state            = VOLTHIUM_STATE_CHARGING,
        .pack_voltage_cV  = 2671,  /* 26.71 V */
        .pack_current_cA  = 1630,  /* +16.30 A */
        .pack_power_W     = 435,
        .soc_a_pct        = 68,
        .soc_b_pct        = 66,
        .v_a_mV           = 13353,
        .v_b_mV           = 13357,
        .i_a_cA           = 1650,
        .i_b_cA           = 1610,
        .temp_a_C         = 23,
        .temp_b_C         = 23,
        .remaining_ah_a_dAh = 1560,
        .remaining_ah_b_dAh = 1380,
        .delta_v_a_mV     = 9,
        .delta_v_b_mV     = 7,
        .minutes_remaining = 229,
        .flags            = VOLTHIUM_FLAG_CHARGING_FETS | VOLTHIUM_FLAG_DISCHARGING_FETS,
        .reserved         = 0,
    };

    uint8_t wire[VOLTHIUM_FRAME_SIZE];
    size_t n = volthium_encode(&body, wire, sizeof(wire));
    EXPECT(n == VOLTHIUM_FRAME_SIZE, "encode produces 43 bytes");
    EXPECT(wire[0] == 0xAA && wire[1] == 0x55, "magic bytes correct");

    volthium_body_t out = {0};
    volthium_decode_result_t rc = volthium_decode(wire, sizeof(wire), &out);
    EXPECT(rc == VOLTHIUM_OK, "decode of valid frame returns OK");
    EXPECT(out.seq == 42, "seq round-trips");
    EXPECT(out.state == VOLTHIUM_STATE_CHARGING, "state round-trips");
    EXPECT(out.pack_voltage_cV == 2671, "pack_voltage round-trips");
    EXPECT(out.pack_current_cA == 1630, "pack_current round-trips");
    EXPECT(out.soc_a_pct == 68 && out.soc_b_pct == 66, "soc round-trips");
    EXPECT(out.minutes_remaining == 229, "minutes_remaining round-trips");
}

static void test_negative_values(void)
{
    /* Discharging case — negative current and power. */
    volthium_body_t body = {
        .version         = VOLTHIUM_VERSION,
        .seq             = 1,
        .state           = VOLTHIUM_STATE_DISCHARGING,
        .pack_voltage_cV = 2640,
        .pack_current_cA = -1550,   /* -15.50 A */
        .pack_power_W    = -410,
        .soc_a_pct       = VOLTHIUM_SENTINEL_U8,
        .soc_b_pct       = VOLTHIUM_SENTINEL_U8,
        .v_a_mV          = VOLTHIUM_SENTINEL_U16,
        .v_b_mV          = VOLTHIUM_SENTINEL_U16,
        .i_a_cA          = VOLTHIUM_SENTINEL_I16,
        .i_b_cA          = VOLTHIUM_SENTINEL_I16,
        .temp_a_C        = -5,
        .temp_b_C        = VOLTHIUM_SENTINEL_I8,
        .remaining_ah_a_dAh = VOLTHIUM_SENTINEL_U16,
        .remaining_ah_b_dAh = VOLTHIUM_SENTINEL_U16,
        .delta_v_a_mV    = VOLTHIUM_SENTINEL_U16,
        .delta_v_b_mV    = VOLTHIUM_SENTINEL_U16,
        .minutes_remaining = VOLTHIUM_SENTINEL_U16,
        .flags           = 0,
        .reserved        = 0,
    };

    uint8_t wire[VOLTHIUM_FRAME_SIZE];
    volthium_encode(&body, wire, sizeof(wire));

    volthium_body_t out = {0};
    volthium_decode_result_t rc = volthium_decode(wire, sizeof(wire), &out);
    EXPECT(rc == VOLTHIUM_OK, "decode of negative-current frame returns OK");
    EXPECT(out.pack_current_cA == -1550, "negative pack_current round-trips");
    EXPECT(out.pack_power_W == -410, "negative pack_power round-trips");
    EXPECT(out.temp_a_C == -5, "negative temperature round-trips");
    EXPECT(!volthium_i16_is_set(out.i_a_cA), "sentinel i_a recognized");
    EXPECT(!volthium_u8_is_set(out.soc_a_pct), "sentinel soc_a recognized");
}

static void test_bad_magic_rejected(void)
{
    uint8_t wire[VOLTHIUM_FRAME_SIZE] = {0x12, 0x34, /* bad magic */};
    volthium_body_t out;
    volthium_decode_result_t rc = volthium_decode(wire, sizeof(wire), &out);
    EXPECT(rc == VOLTHIUM_ERR_BAD_MAGIC, "bad magic rejected");
}

static void test_bit_flip_caught_by_crc(void)
{
    volthium_body_t body = {
        .version = VOLTHIUM_VERSION,
        .seq = 1,
        .pack_voltage_cV = 2600,
    };
    uint8_t wire[VOLTHIUM_FRAME_SIZE];
    volthium_encode(&body, wire, sizeof(wire));

    wire[10] ^= 0x01;   /* flip a bit somewhere in the body */

    volthium_body_t out;
    volthium_decode_result_t rc = volthium_decode(wire, sizeof(wire), &out);
    EXPECT(rc == VOLTHIUM_ERR_CRC_MISMATCH, "bit-flip caught by CRC");
}

static void test_short_buffer_rejected(void)
{
    uint8_t wire[10] = {0xAA, 0x55};
    volthium_body_t out;
    volthium_decode_result_t rc = volthium_decode(wire, sizeof(wire), &out);
    EXPECT(rc == VOLTHIUM_ERR_SHORT_BUFFER, "short buffer rejected");
}

int main(void)
{
    printf("=== volthium_lib wire_protocol C tests ===\n");
    test_crc_known_vector();
    test_crc_empty();
    test_frame_size();
    test_encode_decode_roundtrip();
    test_negative_values();
    test_bad_magic_rejected();
    test_bit_flip_caught_by_crc();
    test_short_buffer_rejected();
    if (g_fail == 0) {
        printf("\nall tests passed ✓\n");
        return 0;
    } else {
        printf("\n%d test(s) FAILED\n", g_fail);
        return 1;
    }
}
