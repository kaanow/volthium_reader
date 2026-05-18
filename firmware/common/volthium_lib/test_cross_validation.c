/* Python ↔ C cross-validation for the wire protocol.
 *
 * Reads the Python-encoded reference frames in test_vectors/, then for
 * each case:
 *
 *   1. Decodes the Python bytes with volthium_decode() and verifies
 *      every field matches the expected values declared below.
 *
 *   2. Re-encodes the same fields with volthium_encode() and asserts
 *      the bytes are IDENTICAL to the Python-encoded reference.
 *
 * If either side fails on any case, the two implementations have drifted
 * and the firmware would mis-interpret frames from the production
 * Python tooling. Both must pass.
 *
 * Build & run (after scripts/gen_test_vectors.py has been run once):
 *     cc -std=c11 -Wall -Wextra -Werror -o test_cross_validation \
 *        test_cross_validation.c wire_protocol.c
 *     ./test_cross_validation
 */

#include "wire_protocol.h"

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static int g_fail = 0;

#define EXPECT(cond, label) do {                            \
    if (cond) {                                              \
        printf("    PASS  %s\n", label);                     \
    } else {                                                 \
        printf("    FAIL  %s  (line %d)\n", label, __LINE__);\
        g_fail++;                                            \
    }                                                        \
} while (0)


typedef struct {
    const char       *name;
    const char       *path;
    volthium_body_t   body;
} cross_case_t;

/* These MUST mirror scripts/gen_test_vectors.py exactly. If the Python
 * test cases change, update both sides. */
static const cross_case_t CASES[] = {
    {
        .name = "charging_realistic",
        .path = "test_vectors/charging_realistic.bin",
        .body = {
            .version = VOLTHIUM_VERSION, .seq = 42, .uptime_ms = 12345,
            .state = VOLTHIUM_STATE_CHARGING,
            .pack_voltage_cV = 2671, .pack_current_cA = 1630, .pack_power_W = 435,
            .soc_a_pct = 68, .soc_b_pct = 66,
            .v_a_mV = 13353, .v_b_mV = 13357, .i_a_cA = 1650, .i_b_cA = 1610,
            .temp_a_C = 23, .temp_b_C = 23,
            .remaining_ah_a_dAh = 1560, .remaining_ah_b_dAh = 1380,
            .delta_v_a_mV = 9, .delta_v_b_mV = 7,
            .minutes_remaining = 229,
            .flags = VOLTHIUM_FLAG_CHARGING_FETS | VOLTHIUM_FLAG_DISCHARGING_FETS,
            .reserved = 0,
        },
    },
    {
        .name = "discharging_with_negatives",
        .path = "test_vectors/discharging_with_negatives.bin",
        .body = {
            .version = VOLTHIUM_VERSION, .seq = 128, .uptime_ms = 999999,
            .state = VOLTHIUM_STATE_DISCHARGING,
            .pack_voltage_cV = 2640, .pack_current_cA = -1550, .pack_power_W = -410,
            .soc_a_pct = 80, .soc_b_pct = 78,
            .v_a_mV = 13200, .v_b_mV = 13200, .i_a_cA = -1540, .i_b_cA = -1560,
            .temp_a_C = -5, .temp_b_C = -5,
            .remaining_ah_a_dAh = 1600, .remaining_ah_b_dAh = 1580,
            .delta_v_a_mV = 12, .delta_v_b_mV = 10,
            .minutes_remaining = 600,
            .flags = VOLTHIUM_FLAG_DISCHARGING_FETS,
            .reserved = 0,
        },
    },
    {
        .name = "full_state",
        .path = "test_vectors/full_state.bin",
        .body = {
            .version = VOLTHIUM_VERSION, .seq = 255, .uptime_ms = 42,
            .state = VOLTHIUM_STATE_FULL,
            .pack_voltage_cV = 2740, .pack_current_cA = 50, .pack_power_W = 14,
            .soc_a_pct = 95, .soc_b_pct = 96,
            .v_a_mV = 13700, .v_b_mV = 13700, .i_a_cA = 50, .i_b_cA = 50,
            .temp_a_C = 25, .temp_b_C = 25,
            .remaining_ah_a_dAh = 2100, .remaining_ah_b_dAh = 2080,
            .delta_v_a_mV = 4, .delta_v_b_mV = 5,
            .minutes_remaining = 0,
            .flags = VOLTHIUM_FLAG_CHARGING_FETS | VOLTHIUM_FLAG_DISCHARGING_FETS,
            .reserved = 0,
        },
    },
    {
        .name = "battery_a_offline",
        .path = "test_vectors/battery_a_offline.bin",
        .body = {
            .version = VOLTHIUM_VERSION, .seq = 1, .uptime_ms = 100,
            .state = VOLTHIUM_STATE_UNKNOWN,
            .pack_voltage_cV = VOLTHIUM_SENTINEL_U16,
            .pack_current_cA = VOLTHIUM_SENTINEL_I16,
            .pack_power_W    = VOLTHIUM_SENTINEL_I16,
            .soc_a_pct = VOLTHIUM_SENTINEL_U8, .soc_b_pct = 72,
            .v_a_mV = VOLTHIUM_SENTINEL_U16, .v_b_mV = 13300,
            .i_a_cA = VOLTHIUM_SENTINEL_I16, .i_b_cA = -320,
            .temp_a_C = VOLTHIUM_SENTINEL_I8, .temp_b_C = 22,
            .remaining_ah_a_dAh = VOLTHIUM_SENTINEL_U16,
            .remaining_ah_b_dAh = 1400,
            .delta_v_a_mV = VOLTHIUM_SENTINEL_U16, .delta_v_b_mV = 8,
            .minutes_remaining = VOLTHIUM_SENTINEL_U16,
            .flags = VOLTHIUM_FLAG_A_UNREACHABLE,
            .reserved = 0,
        },
    },
};

#define NUM_CASES (sizeof(CASES) / sizeof(CASES[0]))


static int read_file(const char *path, uint8_t *buf, size_t buf_len)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) {
        fprintf(stderr, "    cannot open %s — run scripts/gen_test_vectors.py first\n",
                path);
        return -1;
    }
    size_t n = fread(buf, 1, buf_len, f);
    fclose(f);
    return (int)n;
}


static void test_case(const cross_case_t *c)
{
    printf("  case: %s\n", c->name);

    uint8_t py_bytes[VOLTHIUM_FRAME_SIZE + 4];
    int n = read_file(c->path, py_bytes, sizeof(py_bytes));
    if (n != VOLTHIUM_FRAME_SIZE) {
        printf("    FAIL  file size %d != 43\n", n);
        g_fail++;
        return;
    }

    /* === direction 1 === Python-encoded → C-decoded → field check */
    volthium_body_t decoded = {0};
    volthium_decode_result_t rc = volthium_decode(py_bytes, n, &decoded);
    EXPECT(rc == VOLTHIUM_OK, "decoded Python frame without error");

    EXPECT(decoded.version          == c->body.version,            "version");
    EXPECT(decoded.seq              == c->body.seq,                "seq");
    EXPECT(decoded.uptime_ms        == c->body.uptime_ms,          "uptime_ms");
    EXPECT(decoded.state            == c->body.state,              "state");
    EXPECT(decoded.pack_voltage_cV  == c->body.pack_voltage_cV,    "pack_voltage_cV");
    EXPECT(decoded.pack_current_cA  == c->body.pack_current_cA,    "pack_current_cA");
    EXPECT(decoded.pack_power_W     == c->body.pack_power_W,       "pack_power_W");
    EXPECT(decoded.soc_a_pct        == c->body.soc_a_pct,          "soc_a_pct");
    EXPECT(decoded.soc_b_pct        == c->body.soc_b_pct,          "soc_b_pct");
    EXPECT(decoded.v_a_mV           == c->body.v_a_mV,             "v_a_mV");
    EXPECT(decoded.v_b_mV           == c->body.v_b_mV,             "v_b_mV");
    EXPECT(decoded.i_a_cA           == c->body.i_a_cA,             "i_a_cA");
    EXPECT(decoded.i_b_cA           == c->body.i_b_cA,             "i_b_cA");
    EXPECT(decoded.temp_a_C         == c->body.temp_a_C,           "temp_a_C");
    EXPECT(decoded.temp_b_C         == c->body.temp_b_C,           "temp_b_C");
    EXPECT(decoded.remaining_ah_a_dAh == c->body.remaining_ah_a_dAh, "remaining_ah_a_dAh");
    EXPECT(decoded.remaining_ah_b_dAh == c->body.remaining_ah_b_dAh, "remaining_ah_b_dAh");
    EXPECT(decoded.delta_v_a_mV     == c->body.delta_v_a_mV,       "delta_v_a_mV");
    EXPECT(decoded.delta_v_b_mV     == c->body.delta_v_b_mV,       "delta_v_b_mV");
    EXPECT(decoded.minutes_remaining == c->body.minutes_remaining, "minutes_remaining");
    EXPECT(decoded.flags            == c->body.flags,              "flags");

    /* === direction 2 === C encodes the same fields → bytes must equal Python */
    uint8_t c_bytes[VOLTHIUM_FRAME_SIZE];
    size_t enc_n = volthium_encode(&c->body, c_bytes, sizeof(c_bytes));
    EXPECT(enc_n == VOLTHIUM_FRAME_SIZE, "C encode produced 43 bytes");
    int byte_diff = memcmp(c_bytes, py_bytes, VOLTHIUM_FRAME_SIZE);
    if (byte_diff != 0) {
        printf("    FAIL  C-encoded bytes differ from Python bytes\n");
        printf("      python : ");
        for (unsigned i = 0; i < VOLTHIUM_FRAME_SIZE; i++) printf("%02x", py_bytes[i]);
        printf("\n      C      : ");
        for (unsigned i = 0; i < VOLTHIUM_FRAME_SIZE; i++) printf("%02x", c_bytes[i]);
        printf("\n");
        g_fail++;
    } else {
        printf("    PASS  C-encoded bytes byte-identical to Python\n");
    }
}


int main(void)
{
    printf("=== wire-protocol Python ↔ C cross-validation ===\n");
    for (size_t i = 0; i < NUM_CASES; i++) {
        test_case(&CASES[i]);
    }
    if (g_fail == 0) {
        printf("\nall %zu cases passed ✓\n", NUM_CASES);
        return 0;
    }
    printf("\n%d assertion(s) FAILED\n", g_fail);
    return 1;
}
