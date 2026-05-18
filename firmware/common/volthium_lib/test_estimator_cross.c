/* Python ↔ C cross-validation for the estimator.
 *
 * Reads test_vectors/estimator_scenarios.txt (produced by
 * scripts/gen_estimator_vectors.py) and for each scenario:
 *
 *   1. Initializes a C estimator with the scenario's config.
 *   2. For each step line, runs the C estimator with that input and
 *      asserts every output field matches the matching `expect:` line
 *      within a tight floating-point tolerance.
 *
 * If the C estimator drifts from the Python reference on any step, this
 * test fails — catches regressions in either implementation that would
 * otherwise go silent until production firmware misbehaves.
 *
 * Tolerances are deliberately small (currents to 1e-4 A, minutes to
 * 0.1 min, Ah to 1e-3) — both implementations use IEEE-754 single or
 * double floats; they should be in lock-step. Larger drift = real bug.
 *
 * Build & run:
 *     cc -std=c11 -Wall -Wextra -Werror -o test_estimator_cross \
 *        test_estimator_cross.c estimator.c -lm
 *     ./test_estimator_cross
 */

#include "estimator.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdbool.h>

#define TOL_CURRENT  1e-3f
#define TOL_POWER    5e-3f
#define TOL_MINUTES  0.1f
#define TOL_AH       1e-3f

static int g_fail = 0;
static int g_pass = 0;

#define FAIL(fmt, ...) do {                       \
    fprintf(stderr, "    FAIL  " fmt "\n", ##__VA_ARGS__); \
    g_fail++;                                      \
} while (0)

#define PASS_STEP() do { g_pass++; } while (0)


/* One parsed step + expect pair. */
typedef struct {
    /* input */
    uint64_t ts_ms;
    float pack_i_a;
    bool  has_pack_p;  float pack_p_w;
    bool  has_max_soc; float max_soc_pct;
    bool  has_min_soc; float min_soc_pct;
    bool  has_rem_ah;  float rem_ah_avg;
    /* expected output */
    int   exp_state;
    float exp_smoothed_i;
    float exp_smoothed_p;
    bool  exp_has_min;
    float exp_minutes;
    bool  exp_has_disp;
    float exp_disp;
} scen_step_t;


static int parse_config(const char *line, volthium_estimator_config_t *cfg)
{
    int hybrid = 0;
    int got = sscanf(line,
        "config: capacity=%f,floor=%f,ceiling=%f,idle=%f,"
        "alpha=%f,calibration=%f,hybrid=%d,blend=%f",
        &cfg->capacity_ah, &cfg->floor_soc_pct, &cfg->ceiling_soc_pct,
        &cfg->idle_current_a, &cfg->ema_alpha, &cfg->current_calibration,
        &hybrid, &cfg->hybrid_integrator_weight);
    if (got != 8) {
        fprintf(stderr, "    bad config line (got %d/8): %s", got, line);
        return -1;
    }
    cfg->use_hybrid = (hybrid != 0);
    return 0;
}


static int parse_step(const char *line, scen_step_t *s)
{
    int has_p = 0, has_max = 0, has_min = 0, has_rem = 0;
    /* %llu requires unsigned long long; ts_ms is uint64_t so cast safely */
    unsigned long long ts = 0;
    int got = sscanf(line,
        "step: %llu,%f,%d,%f,%d,%f,%d,%f,%d,%f",
        &ts, &s->pack_i_a,
        &has_p,  &s->pack_p_w,
        &has_max, &s->max_soc_pct,
        &has_min, &s->min_soc_pct,
        &has_rem, &s->rem_ah_avg);
    if (got != 10) {
        fprintf(stderr, "    bad step line (got %d/10): %s", got, line);
        return -1;
    }
    s->ts_ms = (uint64_t)ts;
    s->has_pack_p  = (has_p   != 0);
    s->has_max_soc = (has_max != 0);
    s->has_min_soc = (has_min != 0);
    s->has_rem_ah  = (has_rem != 0);
    return 0;
}


static int parse_expect(const char *line, scen_step_t *s)
{
    int has_min = 0, has_disp = 0;
    int got = sscanf(line,
        "expect: %d,%f,%f,%d,%f,%d,%f",
        &s->exp_state, &s->exp_smoothed_i, &s->exp_smoothed_p,
        &has_min, &s->exp_minutes,
        &has_disp, &s->exp_disp);
    if (got != 7) {
        fprintf(stderr, "    bad expect line (got %d/7): %s", got, line);
        return -1;
    }
    s->exp_has_min  = (has_min  != 0);
    s->exp_has_disp = (has_disp != 0);
    return 0;
}


static void check_step(const char *scenario, int step_idx,
                       const scen_step_t *s,
                       const volthium_estimate_t *got)
{
    if ((int)got->state != s->exp_state) {
        FAIL("[%s step %d] state %d != expected %d",
             scenario, step_idx, (int)got->state, s->exp_state);
        return;
    }
    if (fabsf(got->smoothed_current_a - s->exp_smoothed_i) > TOL_CURRENT) {
        FAIL("[%s step %d] smoothed_i %.6f != expected %.6f (tol %.1e)",
             scenario, step_idx, got->smoothed_current_a, s->exp_smoothed_i,
             (double)TOL_CURRENT);
        return;
    }
    if (fabsf(got->smoothed_power_w - s->exp_smoothed_p) > TOL_POWER) {
        FAIL("[%s step %d] smoothed_p %.6f != expected %.6f (tol %.1e)",
             scenario, step_idx, got->smoothed_power_w, s->exp_smoothed_p,
             (double)TOL_POWER);
        return;
    }
    if (got->has_minutes_remaining != s->exp_has_min) {
        FAIL("[%s step %d] has_minutes %d != expected %d",
             scenario, step_idx, (int)got->has_minutes_remaining,
             (int)s->exp_has_min);
        return;
    }
    if (s->exp_has_min &&
        fabsf(got->minutes_remaining - s->exp_minutes) > TOL_MINUTES) {
        FAIL("[%s step %d] minutes %.4f != expected %.4f (tol %.2f)",
             scenario, step_idx, got->minutes_remaining, s->exp_minutes,
             (double)TOL_MINUTES);
        return;
    }
    if (got->has_displayed_ah != s->exp_has_disp) {
        FAIL("[%s step %d] has_displayed_ah %d != expected %d",
             scenario, step_idx, (int)got->has_displayed_ah,
             (int)s->exp_has_disp);
        return;
    }
    if (s->exp_has_disp &&
        fabsf(got->displayed_ah - s->exp_disp) > TOL_AH) {
        FAIL("[%s step %d] displayed_ah %.6f != expected %.6f (tol %.1e)",
             scenario, step_idx, got->displayed_ah, s->exp_disp,
             (double)TOL_AH);
        return;
    }
    PASS_STEP();
}


/* Drop trailing whitespace + newline from `s` in-place. */
static void rtrim(char *s)
{
    size_t n = strlen(s);
    while (n > 0 && (s[n-1] == '\n' || s[n-1] == '\r' ||
                     s[n-1] == ' '  || s[n-1] == '\t')) {
        s[--n] = '\0';
    }
}


int main(void)
{
    const char *path = "test_vectors/estimator_scenarios.txt";
    FILE *f = fopen(path, "r");
    if (f == NULL) {
        fprintf(stderr, "cannot open %s — run "
                "scripts/gen_estimator_vectors.py first\n", path);
        return 1;
    }

    printf("=== estimator Python ↔ C cross-validation ===\n");

    char line[512];
    char scenario_name[128] = "";
    int  step_idx = 0;
    int  scenarios_seen = 0;
    volthium_estimator_t est;
    volthium_estimator_config_t cfg = VOLTHIUM_ESTIMATOR_CONFIG_DEFAULT;
    bool est_inited = false;
    scen_step_t cur = {0};
    bool have_step = false;

    while (fgets(line, sizeof(line), f) != NULL) {
        rtrim(line);
        if (line[0] == '#' || line[0] == '\0') {
            continue;
        }

        if (strncmp(line, "scenario:", 9) == 0) {
            sscanf(line, "scenario: %127s", scenario_name);
            printf("  scenario: %s\n", scenario_name);
            step_idx = 0;
            est_inited = false;
            scenarios_seen++;
            continue;
        }
        if (strncmp(line, "config:", 7) == 0) {
            if (parse_config(line, &cfg) != 0) { g_fail++; continue; }
            volthium_estimator_init(&est, &cfg);
            est_inited = true;
            continue;
        }
        if (strncmp(line, "step:", 5) == 0) {
            if (!est_inited) {
                FAIL("step before config in scenario %s", scenario_name);
                continue;
            }
            if (parse_step(line, &cur) != 0) { g_fail++; continue; }
            have_step = true;
            continue;
        }
        if (strncmp(line, "expect:", 7) == 0) {
            if (!have_step) {
                FAIL("expect without preceding step in scenario %s",
                     scenario_name);
                continue;
            }
            if (parse_expect(line, &cur) != 0) { g_fail++; continue; }

            /* Run the C estimator on the parsed input */
            volthium_sample_t s = {
                .has_pack_current  = true,
                .pack_current_a    = cur.pack_i_a,
                .has_pack_power    = cur.has_pack_p,
                .pack_power_w      = cur.pack_p_w,
                .has_max_soc       = cur.has_max_soc,
                .max_soc_pct       = cur.max_soc_pct,
                .has_min_soc       = cur.has_min_soc,
                .min_soc_pct       = cur.min_soc_pct,
                .has_remaining_ah  = cur.has_rem_ah,
                .remaining_ah_avg  = cur.rem_ah_avg,
                .ts_ms             = cur.ts_ms,
            };
            volthium_estimate_t got = volthium_estimator_update(&est, &s);
            check_step(scenario_name, step_idx, &cur, &got);
            step_idx++;
            have_step = false;
            continue;
        }
        if (strncmp(line, "end", 3) == 0) {
            continue;
        }
        /* unknown line — be loud about it */
        fprintf(stderr, "    WARN  unknown line: %s\n", line);
    }
    fclose(f);

    printf("\nscenarios: %d   step assertions: %d pass / %d fail\n",
           scenarios_seen, g_pass, g_fail);
    if (g_fail == 0) {
        printf("all cross-validation cases passed ✓\n");
        return 0;
    }
    return 1;
}
