/* Volthium time-to-X estimator — C port of volthium/estimator.py.
 *
 * Computes time-to-full or time-to-floor from smoothed pack current,
 * with two modes:
 *
 *   1. SOC-based  (default) — minutes = (capacity * dSOC) / I_eff * 60
 *   2. Hybrid    (use_hybrid=true) — maintains an internal displayed_ah
 *      that integrates I*dt between samples and re-anchors when the
 *      BMS-reported remaining_ah ticks. Strongly recommended for the
 *      production firmware (see docs/hardware/bms_calibration.md).
 *
 * No dynamic allocation; the caller owns the volthium_estimator_t
 * struct. Re-entrant-safe across instances (one per pack).
 */

#ifndef VOLTHIUM_ESTIMATOR_H
#define VOLTHIUM_ESTIMATOR_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    EST_STATE_UNKNOWN     = 0,
    EST_STATE_IDLE        = 1,
    EST_STATE_CHARGING    = 2,
    EST_STATE_DISCHARGING = 3,
    EST_STATE_FULL        = 4,
} est_state_t;

/* Per-pack configuration. Tune at compile time or via init() params. */
typedef struct {
    float capacity_ah;            /* nameplate per-battery; 200 default */
    float floor_soc_pct;          /* "empty" floor; 10 default */
    float ceiling_soc_pct;        /* "full" ceiling; 95 default (LiFePO4 absorption-onset) */
    float idle_current_a;         /* |I| < this => idle state; 0.5 default */
    float ema_alpha;              /* EMA smoothing factor; 0.15 default (smaller = smoother) */
    float current_calibration;    /* multiplier on smoothed I for time math; 1.0 default */
    bool  use_hybrid;             /* if true: anchor displayed_ah on BMS rem_ah */
    float hybrid_integrator_weight; /* blend factor on anchor tick; 0.8 default */
} volthium_estimator_config_t;

/* Sensible defaults — mirrors Python Estimator() with no args. */
#define VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT (volthium_estimator_config_t){ \
    .capacity_ah               = 200.0f, \
    .floor_soc_pct             = 10.0f,  \
    .ceiling_soc_pct           = 95.0f,  \
    .idle_current_a            = 0.5f,   \
    .ema_alpha                 = 0.15f,  \
    .current_calibration       = 1.0f,   \
    .use_hybrid                = false,  \
    .hybrid_integrator_weight  = 0.8f,   \
}

/* Opaque-ish state struct. Initialize via volthium_estimator_init(). */
typedef struct {
    volthium_estimator_config_t cfg;
    float    ema_i_a;             /* smoothed pack current, A */
    float    ema_p_w;             /* smoothed pack power, W */
    bool     ema_initialized;     /* current EMA seeded? */
    bool     ema_power_initialized; /* power EMA seeded? (tracked separately
                                       because a BMS may skip pack_power on
                                       the first sample) */
    /* Hybrid-mode state — only used if cfg.use_hybrid */
    float    displayed_ah;
    float    last_anchor_ah;
    uint64_t last_ts_ms;
    bool     hybrid_initialized;
} volthium_estimator_t;

/* One observation snapshot. Set has_X fields appropriately. */
typedef struct {
    /* Required for any useful estimate: */
    bool     has_pack_current;
    float    pack_current_a;       /* + = charging, - = discharging */

    /* Optional but recommended: */
    bool     has_pack_power;
    float    pack_power_w;

    bool     has_max_soc;
    float    max_soc_pct;          /* limiting battery on charge */
    bool     has_min_soc;
    float    min_soc_pct;          /* limiting battery on discharge */

    /* Hybrid mode wants these: */
    bool     has_remaining_ah;
    float    remaining_ah_avg;     /* (rem_a + rem_b) / 2 */
    uint64_t ts_ms;                /* monotonic milliseconds */
} volthium_sample_t;

/* The estimator's verdict on the current sample. */
typedef struct {
    est_state_t state;
    float       smoothed_current_a;
    float       smoothed_power_w;
    bool        has_minutes_remaining;
    float       minutes_remaining;
    bool        has_displayed_ah;
    float       displayed_ah;
} volthium_estimate_t;

/* Initialize state. Call once at startup. */
void volthium_estimator_init(volthium_estimator_t *e,
                             const volthium_estimator_config_t *cfg);

/* Feed one sample. Returns the current estimate. */
volthium_estimate_t volthium_estimator_update(volthium_estimator_t *e,
                                              const volthium_sample_t *s);

#ifdef __cplusplus
}
#endif

#endif /* VOLTHIUM_ESTIMATOR_H */
