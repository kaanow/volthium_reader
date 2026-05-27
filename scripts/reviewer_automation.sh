#!/usr/bin/env bash
# Reliable reviewer automation runner for volthium_reader.
# Runs independently of the current chat session.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${REPO_DIR}/.reviewer_automation"
PID_FILE="${STATE_DIR}/daemon.pid"
LOCK_DIR="${STATE_DIR}/run.lock"
LOG_FILE="${STATE_DIR}/automation.log"
DUE_FILE="${STATE_DIR}/next_due_epoch"
HEARTBEAT_FILE="${STATE_DIR}/heartbeat_epoch"
STOP_FILE="${STATE_DIR}/stop_requested"

INTERVAL_SEC="${INTERVAL_SEC:-180}"          # 3 minutes
POLL_SEC="${POLL_SEC:-20}"                   # scheduler poll period
MAX_RETRIES="${MAX_RETRIES:-3}"              # per due cycle
RETRY_BACKOFF_SEC="${RETRY_BACKOFF_SEC:-60}" # retry wait
MODEL_ID="${MODEL_ID:-gpt-5.3-codex}"        # pinned model (effective next daemon restart)

PROMPT="Read ${REPO_DIR}/hardware/reviews/REVIEWER.md fully and follow its protocol end-to-end, with this shared-workspace override: do not perform an unconditional git pull step inside the review turn. Assume preflight sync has already run externally. If state is not codex_turn, exit immediately without modifications. If codex_turn, complete exactly one full reviewer iteration including findings append, semaphore handoff, commit, and push."

mkdir -p "${STATE_DIR}"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" | tee -a "${LOG_FILE}" >/dev/null
}

heartbeat() {
  date +%s > "${HEARTBEAT_FILE}"
}

is_running() {
  if [ ! -f "${PID_FILE}" ]; then
    return 1
  fi
  local pid
  pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [ -z "${pid}" ]; then
    return 1
  fi
  if ps -p "${pid}" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

set_next_due() {
  local next_due
  next_due="$(( $(date +%s) + INTERVAL_SEC ))"
  printf '%s\n' "${next_due}" > "${DUE_FILE}"
}

get_due() {
  if [ -f "${DUE_FILE}" ]; then
    cat "${DUE_FILE}" 2>/dev/null || echo 0
  else
    echo 0
  fi
}

run_once() {
  if ! command -v cursor-agent >/dev/null 2>&1; then
    log "ERROR: cursor-agent not found in PATH"
    return 127
  fi

  if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    log "SKIP: run already in progress"
    return 0
  fi
  trap 'rm -rf "${LOCK_DIR}"' RETURN

  log "RUN: starting reviewer iteration attempt"

  # Shared-workspace preflight sync:
  # - fetch remote branch state
  # - fast-forward pull only when strictly behind and not diverged
  # - never block the review turn on divergence (log and continue)
  local branch behind ahead counts
  branch="$(git -C "${REPO_DIR}" symbolic-ref --short HEAD 2>/dev/null || true)"
  if [ -n "${branch}" ]; then
    if git -C "${REPO_DIR}" fetch origin "${branch}" >>"${LOG_FILE}" 2>&1; then
      counts="$(git -C "${REPO_DIR}" rev-list --left-right --count "HEAD...origin/${branch}" 2>/dev/null || echo "0 0")"
      ahead="${counts%% *}"
      behind="${counts##* }"
      log "SYNC: branch=${branch} ahead=${ahead} behind=${behind}"
      if [ "${behind}" -gt 0 ] && [ "${ahead}" -eq 0 ]; then
        if git -C "${REPO_DIR}" pull --ff-only origin "${branch}" >>"${LOG_FILE}" 2>&1; then
          log "SYNC: fast-forward pull applied"
        else
          log "SYNC: WARN fast-forward pull failed; continuing turn"
        fi
      elif [ "${behind}" -gt 0 ] && [ "${ahead}" -gt 0 ]; then
        log "SYNC: WARN diverged from origin/${branch}; continuing without pull"
      fi
    else
      log "SYNC: WARN fetch failed; continuing turn"
    fi
  else
    log "SYNC: WARN could not determine current branch; continuing turn"
  fi

  local rc=0
  (
    cd "${REPO_DIR}"
    cursor-agent -p --trust --yolo --output-format text --model "${MODEL_ID}" "${PROMPT}"
  ) >>"${LOG_FILE}" 2>&1 || rc=$?

  if [ "${rc}" -eq 0 ]; then
    log "RUN: completed successfully"
    set_next_due
    return 0
  fi

  log "RUN: failed with exit code ${rc}"
  return "${rc}"
}

run_due_cycle() {
  local attempt=1
  while [ "${attempt}" -le "${MAX_RETRIES}" ]; do
    if run_once; then
      return 0
    fi
    if [ "${attempt}" -lt "${MAX_RETRIES}" ]; then
      log "RETRY: attempt ${attempt}/${MAX_RETRIES} failed; sleeping ${RETRY_BACKOFF_SEC}s"
      sleep "${RETRY_BACKOFF_SEC}"
    fi
    attempt="$((attempt + 1))"
  done
  log "CYCLE: all retries exhausted; scheduling next regular interval"
  set_next_due
  return 1
}

daemon_loop() {
  log "DAEMON: worker started (interval=${INTERVAL_SEC}s poll=${POLL_SEC}s retries=${MAX_RETRIES})"
  heartbeat
  if [ ! -f "${DUE_FILE}" ]; then
    # Start with an immediate run when first launched.
    printf '%s\n' "$(date +%s)" > "${DUE_FILE}"
  fi

  while true; do
    if [ -f "${STOP_FILE}" ]; then
      log "DAEMON: stop requested; worker exiting"
      return 0
    fi
    local now due
    now="$(date +%s)"
    due="$(get_due)"
    if [ "${now}" -ge "${due}" ]; then
      log "DAEMON: due reached (now=${now} due=${due})"
      run_due_cycle || true
    fi
    heartbeat
    sleep "${POLL_SEC}"
  done
}

supervisor_loop() {
  trap 'log "DAEMON: supervisor got termination signal"; rm -f "${PID_FILE}"' INT TERM HUP
  log "DAEMON: supervisor started (pid=$$)"
  heartbeat
  while true; do
    if [ -f "${STOP_FILE}" ]; then
      log "DAEMON: supervisor stop flag seen; exiting"
      rm -f "${STOP_FILE}"
      rm -f "${PID_FILE}"
      return 0
    fi
    daemon_loop || true
    if [ -f "${STOP_FILE}" ]; then
      continue
    fi
    log "DAEMON: worker exited unexpectedly; restarting in 5s"
    sleep 5
  done
}

start_daemon() {
  if is_running; then
    log "DAEMON: already running (pid=$(cat "${PID_FILE}"))"
    echo "already running"
    return 0
  fi
  rm -f "${STOP_FILE}"
  nohup "$0" supervise >>"${LOG_FILE}" 2>&1 &
  local pid="$!"
  printf '%s\n' "${pid}" > "${PID_FILE}"
  log "DAEMON: launched (pid=${pid})"
  echo "started pid=${pid}"
}

stop_daemon() {
  if ! is_running; then
    rm -f "${PID_FILE}"
    echo "not running"
    return 0
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  touch "${STOP_FILE}"
  kill "${pid}" >/dev/null 2>&1 || true
  sleep 1
  if ps -p "${pid}" >/dev/null 2>&1; then
    kill -9 "${pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${PID_FILE}"
  rm -f "${STOP_FILE}"
  log "DAEMON: stopped (pid=${pid})"
  echo "stopped"
}

status_daemon() {
  local due due_human hb hb_age
  due="$(get_due)"
  if [ "${due}" -gt 0 ]; then
    due_human="$(date -r "${due}" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null || echo "${due}")"
  else
    due_human="unset"
  fi
  if [ -f "${HEARTBEAT_FILE}" ]; then
    hb="$(cat "${HEARTBEAT_FILE}" 2>/dev/null || echo 0)"
    if [ "${hb}" -gt 0 ]; then
      hb_age="$(( $(date +%s) - hb ))s"
    else
      hb_age="unknown"
    fi
  else
    hb_age="none"
  fi

  if is_running; then
    echo "running pid=$(cat "${PID_FILE}") next_due=${due_human} heartbeat_age=${hb_age}"
  else
    echo "stopped next_due=${due_human} heartbeat_age=${hb_age}"
  fi
  echo "log=${LOG_FILE}"
}

usage() {
  cat <<'EOF'
Usage:
  scripts/reviewer_automation.sh start
  scripts/reviewer_automation.sh stop
  scripts/reviewer_automation.sh status
  scripts/reviewer_automation.sh run-now
  scripts/reviewer_automation.sh daemon
  scripts/reviewer_automation.sh supervise

Environment overrides:
  INTERVAL_SEC, POLL_SEC, MAX_RETRIES, RETRY_BACKOFF_SEC, MODEL_ID
EOF
}

cmd="${1:-}"
case "${cmd}" in
  start)   start_daemon ;;
  stop)    stop_daemon ;;
  status)  status_daemon ;;
  run-now) run_due_cycle ;;
  daemon)  daemon_loop ;;
  supervise) supervisor_loop ;;
  *)       usage; exit 1 ;;
esac
