/* Volthium wire protocol — C port of volthium/wire_protocol.py.
 *
 * Byte-for-byte compatible with the Python reference. Tests for the
 * Python side are in tests/test_wire_protocol.py — the same vectors
 * (e.g. CRC-CCITT-FALSE("123456789") == 0x29B1) hold here.
 *
 * Frame layout (43 bytes total) — see docs/firmware/architecture.md
 * and tests/test_wire_protocol.py for the canonical reference.
 */

#ifndef VOLTHIUM_WIRE_PROTOCOL_H
#define VOLTHIUM_WIRE_PROTOCOL_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define VOLTHIUM_FRAME_SIZE   43U
#define VOLTHIUM_BODY_SIZE    39U
#define VOLTHIUM_MAGIC_0      0xAAU
#define VOLTHIUM_MAGIC_1      0x55U
#define VOLTHIUM_VERSION      1U

/* state enum — keep in lockstep with STATE_* in volthium/wire_protocol.py */
typedef enum {
    VOLTHIUM_STATE_UNKNOWN     = 0,
    VOLTHIUM_STATE_IDLE        = 1,
    VOLTHIUM_STATE_CHARGING    = 2,
    VOLTHIUM_STATE_DISCHARGING = 3,
    VOLTHIUM_STATE_FULL        = 4,
} volthium_state_t;

/* flag bits (within frame.flags) */
#define VOLTHIUM_FLAG_A_UNREACHABLE    (1U << 0)
#define VOLTHIUM_FLAG_B_UNREACHABLE    (1U << 1)
#define VOLTHIUM_FLAG_A_PROBLEM        (1U << 2)
#define VOLTHIUM_FLAG_B_PROBLEM        (1U << 3)
#define VOLTHIUM_FLAG_CHARGING_FETS    (1U << 4)
#define VOLTHIUM_FLAG_DISCHARGING_FETS (1U << 5)

/* Sentinel values that map back to "unknown" / None in Python. */
#define VOLTHIUM_SENTINEL_U8   0xFFU
#define VOLTHIUM_SENTINEL_U16  0xFFFFU
#define VOLTHIUM_SENTINEL_I8   ((int8_t)(-128))
#define VOLTHIUM_SENTINEL_I16  ((int16_t)(-32768))

/* On-wire frame layout. All multi-byte fields LITTLE-ENDIAN.
 * Use the encoded representation directly when reading from RS-485,
 * convert to "natural" units (volts, amps, percent) only when
 * computing or displaying. */
typedef struct __attribute__((packed)) {
    uint8_t  version;
    uint8_t  seq;
    uint32_t uptime_ms;
    uint8_t  state;                   /* volthium_state_t */
    uint16_t pack_voltage_cV;         /* *100; sentinel U16 */
    int16_t  pack_current_cA;         /* *100; sentinel I16 */
    int16_t  pack_power_W;            /* watts; sentinel I16 */
    uint8_t  soc_a_pct;               /* 0..100; sentinel U8 */
    uint8_t  soc_b_pct;
    uint16_t v_a_mV;                  /* *1000; sentinel U16 */
    uint16_t v_b_mV;
    int16_t  i_a_cA;                  /* *100; sentinel I16 */
    int16_t  i_b_cA;
    int8_t   temp_a_C;                /* sentinel I8 */
    int8_t   temp_b_C;
    uint16_t remaining_ah_a_dAh;      /* *10; sentinel U16 */
    uint16_t remaining_ah_b_dAh;
    uint16_t delta_v_a_mV;            /* mV; sentinel U16 */
    uint16_t delta_v_b_mV;
    uint16_t minutes_remaining;       /* minutes; sentinel U16 */
    uint16_t flags;
    uint16_t reserved;
} volthium_body_t;

_Static_assert(sizeof(volthium_body_t) == VOLTHIUM_BODY_SIZE,
               "volthium_body_t must be 39 bytes — check pragma pack");

typedef struct __attribute__((packed)) {
    uint8_t         magic[2];         /* {0xAA, 0x55} */
    volthium_body_t body;
    uint16_t        crc16;            /* CRC-16/CCITT-FALSE over body */
} volthium_frame_t;

_Static_assert(sizeof(volthium_frame_t) == VOLTHIUM_FRAME_SIZE,
               "volthium_frame_t must be 43 bytes");

/* CRC-16/CCITT-FALSE — polynomial 0x1021, init 0xFFFF, no reflection.
 * Implemented in crc16.c. Test vector: crc16_ccitt("123456789") == 0x29B1. */
uint16_t volthium_crc16_ccitt(const uint8_t *data, size_t len);

/* Encode a body into a full 43-byte frame (magic + body + CRC) at *out.
 * Returns the number of bytes written (always VOLTHIUM_FRAME_SIZE) on
 * success, 0 on error (out_len too small). */
size_t volthium_encode(const volthium_body_t *body, uint8_t *out, size_t out_len);

/* Decode validation — returns true on a well-formed frame.
 * On success, *body_out is populated. Caller is responsible for
 * mapping sentinels back to "unknown" at the application layer. */
typedef enum {
    VOLTHIUM_OK                = 0,
    VOLTHIUM_ERR_SHORT_BUFFER  = 1,
    VOLTHIUM_ERR_BAD_MAGIC     = 2,
    VOLTHIUM_ERR_CRC_MISMATCH  = 3,
    VOLTHIUM_ERR_VERSION       = 4,
} volthium_decode_result_t;

volthium_decode_result_t volthium_decode(const uint8_t *in, size_t in_len,
                                         volthium_body_t *body_out);

/* Convenience helpers — convert sentinel-vs-real-value at the
 * application boundary. */
static inline bool volthium_u8_is_set(uint8_t v)
    { return v != VOLTHIUM_SENTINEL_U8; }
static inline bool volthium_u16_is_set(uint16_t v)
    { return v != VOLTHIUM_SENTINEL_U16; }
static inline bool volthium_i16_is_set(int16_t v)
    { return v != VOLTHIUM_SENTINEL_I16; }

#ifdef __cplusplus
}
#endif

#endif /* VOLTHIUM_WIRE_PROTOCOL_H */
