/* C implementation of the Volthium estimator. See estimator.h.
 *
 * Math is intentionally identical to volthium/estimator.py — the Python
 * test suite is the spec. Both implementations should produce the same
 * minutes_remaining for the same sequence of samples (modulo floating-
 * point precision).
 */

#include "estimator.h"

#include <math.h>
#include <string.h>

void volthium_estimator_init(volthium_estimator_t *e,
                             const volthium_estimator_config_t *cfg)
{
    if (e == NULL) {
        return;
    }
    memset(e, 0, sizeof(*e));
    if (cfg != NULL) {
        e->cfg = *cfg;
    } else {
        e->cfg = VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT;
    }
    e->ema_initialized = false;
    e->ema_power_initialized = false;
    e->hybrid_initialized = false;
}

static void update_ema(float *ema, bool *init, float sample, float alpha)
{
    if (!*init) {
        *ema = sample;
        *init = true;
    } else {
        *ema = alpha * sample + (1.0f - alpha) * (*ema);
    }
}

/* Maintain the hybrid displayed_ah. Returns the current value. */
static float update_hybrid(volthium_estimator_t *e, const volthium_sample_t *s)
{
    /* Need at least one anchor reading to seed. */
    if (!e->hybrid_initialized) {
        if (s->has_remaining_ah) {
            e->displayed_ah = s->remaining_ah_avg;
            e->last_anchor_ah = s->remaining_ah_avg;
            e->last_ts_ms = s->ts_ms;
            e->hybrid_initialized = true;
        }
        return e->displayed_ah;
    }

    /* Integrate current * dt to advance the displayed value. */
    if (s->has_pack_current && s->ts_ms > e->last_ts_ms) {
        uint64_t dt_ms = s->ts_ms - e->last_ts_ms;
        /* Cap dt to avoid huge jumps from clock changes / gaps. */
        if (dt_ms < 600000ULL) {   /* < 10 min */
            float dt_s = (float)dt_ms / 1000.0f;
            e->displayed_ah += s->pack_current_a * dt_s / 3600.0f;
        }
        e->last_ts_ms = s->ts_ms;
    }

    /* Re-anchor when the BMS reports a different value than last seen. */
    if (s->has_remaining_ah && s->remaining_ah_avg != e->last_anchor_ah) {
        float w = e->cfg.hybrid_integrator_weight;
        e->displayed_ah = w * e->displayed_ah + (1.0f - w) * s->remaining_ah_avg;
        e->last_anchor_ah = s->remaining_ah_avg;
    }

    return e->displayed_ah;
}

volthium_estimate_t volthium_estimator_update(volthium_estimator_t *e,
                                              const volthium_sample_t *s)
{
    volthium_estimate_t out = {
        .state = EST_STATE_UNKNOWN,
        .smoothed_current_a = 0.0f,
        .smoothed_power_w = 0.0f,
        .has_minutes_remaining = false,
        .minutes_remaining = 0.0f,
        .has_displayed_ah = false,
        .displayed_ah = 0.0f,
    };

    if (e == NULL || s == NULL || !s->has_pack_current) {
        return out;
    }

    update_ema(&e->ema_i_a, &e->ema_initialized, s->pack_current_a, e->cfg.ema_alpha);
    if (s->has_pack_power) {
        /* Power EMA tracks its own init state — the BMS may skip pack_power
         * on the first sample and only start reporting it later, in which
         * case the first power sample must seed the EMA (not blend with 0).
         * Earlier piggyback-on-ema_initialized was wrong for this reason
         * and caused a factor-of-(1/alpha) scaling on the first power
         * sample. Caught by tests/test_estimator_cross.c. */
        update_ema(&e->ema_p_w, &e->ema_power_initialized,
                   s->pack_power_w, e->cfg.ema_alpha);
    }

    out.smoothed_current_a = e->ema_i_a;
    out.smoothed_power_w   = e->ema_p_w;

    /* Hybrid bookkeeping runs regardless of state. */
    if (e->cfg.use_hybrid) {
        out.displayed_ah = update_hybrid(e, s);
        out.has_displayed_ah = e->hybrid_initialized;
    }

    float si = e->ema_i_a;
    if (fabsf(si) < e->cfg.idle_current_a) {
        out.state = EST_STATE_IDLE;
        return out;
    }

    float eff_i = si * e->cfg.current_calibration;

    if (si > 0.0f) {
        /* Charging — limited by the higher-SOC battery. */
        if (!s->has_max_soc) {
            out.state = EST_STATE_CHARGING;
            return out;
        }
        if (s->max_soc_pct >= e->cfg.ceiling_soc_pct) {
            out.state = EST_STATE_FULL;
            out.has_minutes_remaining = true;
            out.minutes_remaining = 0.0f;
            return out;
        }
        float ah_needed;
        if (out.has_displayed_ah) {
            ah_needed = (e->cfg.capacity_ah * e->cfg.ceiling_soc_pct / 100.0f) - out.displayed_ah;
        } else {
            ah_needed = e->cfg.capacity_ah * (e->cfg.ceiling_soc_pct - s->max_soc_pct) / 100.0f;
        }
        out.state = EST_STATE_CHARGING;
        if (eff_i > 0.0f && ah_needed > 0.0f) {
            out.has_minutes_remaining = true;
            out.minutes_remaining = (ah_needed / eff_i) * 60.0f;
        }
        return out;
    }

    /* Discharging — limited by the lower-SOC battery. */
    if (!s->has_min_soc) {
        out.state = EST_STATE_DISCHARGING;
        return out;
    }
    float ah_left;
    if (out.has_displayed_ah) {
        ah_left = out.displayed_ah - (e->cfg.capacity_ah * e->cfg.floor_soc_pct / 100.0f);
    } else {
        ah_left = e->cfg.capacity_ah * (s->min_soc_pct - e->cfg.floor_soc_pct) / 100.0f;
    }
    out.state = EST_STATE_DISCHARGING;
    if (eff_i < 0.0f && ah_left > 0.0f) {
        out.has_minutes_remaining = true;
        out.minutes_remaining = (ah_left / -eff_i) * 60.0f;
    }
    return out;
}
