# Design: close two gaps in alerting

Draft 2026-08-08. **Not built.** Found while asking a structural question:
*what happens to this system if the 2-hourly checks stop?*

Mostly the answer is fine — the guard, the loggers and the uploaders are all
systemd services with `Restart=always`, and they carry on. But the paging
path has two holes, and the second one undercuts something built two days ago.

## Gap 1: you cannot tell whether alerting is armed

`StalenessMonitor` and `EventAlertMonitor` are wired into the FastAPI
lifespan, and both are **silently disabled unless `STALENESS_WEBHOOK_URL` is
set** (`config.py:77`, default `""`). That is a reasonable default.

What is not reasonable: **nothing observable says which state we are in.**
`/healthz` returns the literal string `ok` and nothing else. From outside there
is no way to distinguish "alerting armed and quiet" from "alerting was never
configured and never will fire".

That is the same failure shape as the health check that truncated silently on
2026-08-07 — a monitor whose silence is ambiguous is not a monitor. The
difference is that this one has been ambiguous the whole time.

**Fix:** report alerting state without leaking the URL, which is a secret.

    GET /healthz  ->  ok alerting=on   (or alerting=off)

Anything that consumes `/healthz` today treats a 200 as healthy and ignores
the body, so appending to it is safe. `status_check.py` should assert
`alerting=on` and say so in its bottom line, so a disabled alerter shows up in
the routine check rather than at the moment it was needed.

## Gap 2: nothing pages on the Xanbus event stream

`EventAlertMonitor` watches **`ble_events`** — `adapter_pin_failed` and
`wedge_snapshot` — which are the BLE-era failure modes. It predates every
piece of solar work and reads a table the solar path does not write to.

`xanbus_events` has **no alert rules at all.** So none of these page anyone:

| event | why it matters |
|---|---|
| **`xanbus_config_changed`** | a charge setpoint moved that we did not move |
| `latch_fix_result` `recovered=false` | the bounce did not work |
| `latch_fix_denied` / `latch_fix_aborted` | lost write authority, or could not claim an address |
| `latch_guard_skipped` reason=daily cap | a latch that will not clear — explicitly "needs a human" |

**The first line is the sharp one.** `xanbus_config_watch.py` was built on
2026-08-06 with the stated reason that equalize sits at **32 V — 4.0 V/cell on
an LFP bank** — is one UI click from being re-enabled, "and nothing currently
alarms on it". It now detects that change and writes an event.

And then nothing alarms on it. The event lands in a table and waits to be
read. I built the detector and never connected it to the bell, which means for
two days the reassurance has been thinner than it looked.

## Rules, and what deliberately does NOT alert

    max      xanbus_config_changed          any charge setpoint moved
    high     latch_fix_result recovered=false
    high     latch_fix_denied | latch_fix_aborted
    high     latch_guard_skipped reason="daily cap reached"
    medium   still clamped >45 min with no successful fix

**No alert** for ordinary `mppt_latched`, `latch_detected`, or
`latch_fix_result recovered=true`. Those happen most days, the guard handles
them unattended, and paging on them teaches the operator to ignore the
channel. Alert on what needs a human, not on what the system is handling —
otherwise the one message that matters arrives in a stream of noise.

The `medium` rule is the safety net for the case the others miss: the guard
never acted at all, for whatever reason, and the array has been dead for the
better part of an hour.

## Implementation notes

`EventAlertMonitor` already has the shape this needs — poll on an interval,
diff against in-memory state, alert on transitions only, one webhook. The work
is:

1. Generalise its DAO dependency from `recent_events` (ble_events) to also
   read `recent_xanbus_events`, which exists and now takes a comma-separated
   event list, so one query fetches exactly the alertable kinds.
2. A rule table rather than the current per-kind methods, since there are now
   two streams and five rules.
3. De-duplication by `(event, ts)` so a repeated poll does not re-page — the
   existing `last_*_alerted` pattern.

None of it touches the Pi or the bus. It is server-side, and the blast radius
of getting it wrong is a spurious notification.

## Gap 1: CLOSED 2026-08-08, and the answer matters

`/healthz` now reports `ok alerting=on|off` and `status_check.py` asserts it
every run. Production answers **`alerting=on`** — the webhook has been
configured all along, so the staleness monitor and the BLE event rules have
been live and working this whole time.

That makes gap 2 the entire remaining story, and sharpens it: there is a
**functioning paging path sitting right there**, watching `ble_events`, while
the config watcher writes `xanbus_config_changed` into a table nothing
watches. The bell works. It is just not wired to the newest detector.
