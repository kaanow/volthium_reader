/* Standalone test for the C estimator port.
 *
 * Mirrors tests/test_estimator.py — both Python and C must agree on the
 * same input → output mappings.
 *
 * Build & run:
 *     cc -std=c11 -Wall -Wextra -Werror -o test_estimator \
 *        test_estimator.c estimator.c -lm
 *     ./test_estimator
 */

#include "estimator.h"

#include <math.h>
#include <stdio.h>
#include <stdint.h>

static int g_fail = 0;

#define EXPECT(cond, label) do {                            \
    if (cond) {                                              \
        printf("  PASS  %s\n", label);                       \
    } else {                                                 \
        printf("  FAIL  %s  (line %d)\n", label, __LINE__);  \
        g_fail++;                                            \
    }                                                        \
} while (0)

#define APPROX(a, b, eps) (fabsf((a) - (b)) < (eps))


/* Build a sample with sensible defaults; caller overrides fields it cares about. */
static volthium_sample_t make_sample(float i, float max_soc, float min_soc)
{
    volthium_sample_t s = {0};
    s.has_pack_current = true;     s.pack_current_a = i;
    s.has_pack_power   = true;     s.pack_power_w = i * 26.4f;
    s.has_max_soc      = true;     s.max_soc_pct = max_soc;
    s.has_min_soc      = true;     s.min_soc_pct = min_soc;
    return s;
}

/* Push the EMA through enough samples to settle. */
static volthium_estimate_t settle(volthium_estimator_t *e, volthium_sample_t s)
{
    volthium_estimate_t out = {0};
    for (int i = 0; i < 60; i++) {
        out = volthium_estimator_update(e, &s);
    }
    return out;
}


static void test_charging_settles(void)
{
    volthium_estimator_t e;
    volthium_estimator_init(&e, NULL);
    volthium_sample_t s = make_sample(20.0f, 80.0f, 80.0f);
    volthium_estimate_t out = settle(&e, s);
    EXPECT(out.state == EST_STATE_CHARGING, "charging state");
    /* ah_needed = 200 * (95-80)/100 = 30; minutes = 30/20*60 = 90 */
    EXPECT(out.has_minutes_remaining, "has minutes");
    EXPECT(APPROX(out.minutes_remaining, 90.0f, 0.5f), "charge time ~ 90 min");
}

static void test_discharging_settles(void)
{
    volthium_estimator_t e;
    volthium_estimator_init(&e, NULL);
    volthium_sample_t s = make_sample(-10.0f, 80.0f, 80.0f);
    volthium_estimate_t out = settle(&e, s);
    EXPECT(out.state == EST_STATE_DISCHARGING, "discharging state");
    /* ah_left = 200 * (80-10)/100 = 140; minutes = 140/10*60 = 840 */
    EXPECT(APPROX(out.minutes_remaining, 840.0f, 1.0f), "discharge time ~ 840 min");
}

static void test_idle(void)
{
    volthium_estimator_t e;
    volthium_estimator_init(&e, NULL);
    volthium_sample_t s = make_sample(0.2f, 80.0f, 80.0f);
    volthium_estimate_t out = settle(&e, s);
    EXPECT(out.state == EST_STATE_IDLE, "idle below threshold");
    EXPECT(!out.has_minutes_remaining, "no minutes in idle");
}

static void test_full(void)
{
    volthium_estimator_t e;
    volthium_estimator_init(&e, NULL);
    volthium_sample_t s = make_sample(5.0f, 95.0f, 95.0f);
    volthium_estimate_t out = settle(&e, s);
    EXPECT(out.state == EST_STATE_FULL, "full at ceiling");
    EXPECT(out.has_minutes_remaining && out.minutes_remaining == 0.0f, "minutes = 0 in full");
}

static void test_calibration(void)
{
    volthium_estimator_t e_base, e_cal;
    volthium_estimator_init(&e_base, NULL);
    volthium_estimator_config_t cfg_cal = VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT;
    cfg_cal.current_calibration = 1.11f;
    volthium_estimator_init(&e_cal, &cfg_cal);

    volthium_sample_t s = make_sample(20.0f, 80.0f, 80.0f);
    volthium_estimate_t base = settle(&e_base, s);
    volthium_estimate_t cal  = settle(&e_cal,  s);
    EXPECT(cal.minutes_remaining < base.minutes_remaining,
           "calibration > 1 shrinks time-to-full");
    /* ratio should be ~1/1.11 */
    float r = cal.minutes_remaining / base.minutes_remaining;
    EXPECT(APPROX(r, 1.0f / 1.11f, 0.01f), "ratio ~ 1/calibration");
    /* smoothed_current must be the RAW value, not the calibrated one */
    EXPECT(APPROX(cal.smoothed_current_a, 20.0f, 0.5f),
           "smoothed_current is raw, not multiplied by calibration");
}

static void test_hybrid_seeds(void)
{
    volthium_estimator_t e;
    volthium_estimator_config_t cfg = VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT;
    cfg.use_hybrid = true;
    volthium_estimator_init(&e, &cfg);

    volthium_sample_t s = make_sample(0.0f, 80.0f, 80.0f);
    s.has_remaining_ah = true;
    s.remaining_ah_avg = 145.0f;
    s.ts_ms = 0;

    volthium_estimate_t out = volthium_estimator_update(&e, &s);
    EXPECT(out.has_displayed_ah, "hybrid initialized");
    EXPECT(APPROX(out.displayed_ah, 145.0f, 0.01f), "seeds from anchor");
}

static void test_hybrid_integrator_advances(void)
{
    volthium_estimator_t e;
    volthium_estimator_config_t cfg = VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT;
    cfg.use_hybrid = true;
    volthium_estimator_init(&e, &cfg);

    /* Seed at 100 Ah */
    volthium_sample_t s = make_sample(10.0f, 80.0f, 80.0f);
    s.has_remaining_ah = true;
    s.remaining_ah_avg = 100.0f;
    s.ts_ms = 0;
    volthium_estimator_update(&e, &s);

    /* 60 samples × 10s = 600s = 10 min at +10A → +1.667 Ah */
    volthium_estimate_t out = {0};
    for (int i = 1; i <= 60; i++) {
        s.ts_ms = (uint64_t)i * 10000ULL;
        out = volthium_estimator_update(&e, &s);
    }
    float expected = 100.0f + 10.0f * 600.0f / 3600.0f;
    EXPECT(APPROX(out.displayed_ah, expected, 0.1f),
           "integrator advances 100 + 10A*10min/h");
}

static void test_hybrid_anchor_blends(void)
{
    volthium_estimator_t e;
    volthium_estimator_config_t cfg = VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT;
    cfg.use_hybrid = true;
    cfg.hybrid_integrator_weight = 0.8f;
    volthium_estimator_init(&e, &cfg);

    volthium_sample_t s = make_sample(60.0f, 70.0f, 70.0f);
    s.has_remaining_ah = true;
    s.remaining_ah_avg = 100.0f;
    s.ts_ms = 0;
    volthium_estimator_update(&e, &s);

    /* After 30s at +60A integrator says 100 + 60*30/3600 = 100.5.
     * Anchor ticks to 102 → blended: 0.8*100.5 + 0.2*102 = 100.8 */
    s.ts_ms = 30000;
    s.remaining_ah_avg = 102.0f;
    volthium_estimate_t out = volthium_estimator_update(&e, &s);
    EXPECT(APPROX(out.displayed_ah, 100.8f, 0.05f),
           "anchor blend = 0.8*integrator + 0.2*anchor");
}

static void test_legacy_mode_no_displayed_ah(void)
{
    volthium_estimator_t e;
    volthium_estimator_init(&e, NULL);   /* use_hybrid = false (default) */
    volthium_sample_t s = make_sample(20.0f, 80.0f, 80.0f);
    volthium_estimate_t out = settle(&e, s);
    EXPECT(!out.has_displayed_ah, "legacy mode never exposes displayed_ah");
}


int main(void)
{
    printf("=== volthium_lib estimator C tests ===\n");
    test_charging_settles();
    test_discharging_settles();
    test_idle();
    test_full();
    test_calibration();
    test_hybrid_seeds();
    test_hybrid_integrator_advances();
    test_hybrid_anchor_blends();
    test_legacy_mode_no_displayed_ah();
    if (g_fail == 0) {
        printf("\nall tests passed ✓\n");
        return 0;
    } else {
        printf("\n%d test(s) FAILED\n", g_fail);
        return 1;
    }
}
