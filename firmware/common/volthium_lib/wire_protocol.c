/* C implementation of the Volthium wire protocol. See wire_protocol.h. */

#include "wire_protocol.h"
#include <string.h>

uint16_t volthium_crc16_ccitt(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFFU;
    for (size_t i = 0; i < len; i++) {
        crc ^= ((uint16_t)data[i]) << 8;
        for (int bit = 0; bit < 8; bit++) {
            if (crc & 0x8000U) {
                crc = (uint16_t)((crc << 1) ^ 0x1021U);
            } else {
                crc = (uint16_t)(crc << 1);
            }
        }
    }
    return crc;
}

size_t volthium_encode(const volthium_body_t *body, uint8_t *out, size_t out_len)
{
    if (out == NULL || body == NULL || out_len < VOLTHIUM_FRAME_SIZE) {
        return 0;
    }

    out[0] = VOLTHIUM_MAGIC_0;
    out[1] = VOLTHIUM_MAGIC_1;
    memcpy(&out[2], body, VOLTHIUM_BODY_SIZE);

    /* Stamp version in case caller forgot. */
    out[2] = VOLTHIUM_VERSION;

    uint16_t crc = volthium_crc16_ccitt(&out[2], VOLTHIUM_BODY_SIZE);
    out[2 + VOLTHIUM_BODY_SIZE]     = (uint8_t)(crc & 0xFFU);
    out[2 + VOLTHIUM_BODY_SIZE + 1] = (uint8_t)((crc >> 8) & 0xFFU);

    return VOLTHIUM_FRAME_SIZE;
}

volthium_decode_result_t volthium_decode(const uint8_t *in, size_t in_len,
                                         volthium_body_t *body_out)
{
    if (in == NULL || body_out == NULL) {
        return VOLTHIUM_ERR_SHORT_BUFFER;
    }
    if (in_len < VOLTHIUM_FRAME_SIZE) {
        return VOLTHIUM_ERR_SHORT_BUFFER;
    }
    if (in[0] != VOLTHIUM_MAGIC_0 || in[1] != VOLTHIUM_MAGIC_1) {
        return VOLTHIUM_ERR_BAD_MAGIC;
    }

    uint16_t got_crc = (uint16_t)in[2 + VOLTHIUM_BODY_SIZE]
                     | ((uint16_t)in[2 + VOLTHIUM_BODY_SIZE + 1] << 8);
    uint16_t want_crc = volthium_crc16_ccitt(&in[2], VOLTHIUM_BODY_SIZE);
    if (got_crc != want_crc) {
        return VOLTHIUM_ERR_CRC_MISMATCH;
    }

    memcpy(body_out, &in[2], VOLTHIUM_BODY_SIZE);

    if (body_out->version != VOLTHIUM_VERSION) {
        return VOLTHIUM_ERR_VERSION;
    }

    return VOLTHIUM_OK;
}
