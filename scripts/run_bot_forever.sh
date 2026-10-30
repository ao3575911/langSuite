#!/usr/bin/env bash
# Keep the langsuite Telegram bot running: restart on exit with backoff.
# The token comes only from LANGSUITE_TELEGRAM_TOKEN in the environment; it is never written here.
# Usage: nohup scripts/run_bot_forever.sh >/dev/null 2>&1 &   Stop: kill the PID in $PIDFILE.
set -u
LOG="${LANGSUITE_BOT_LOG:-$HOME/langsuite_bot.log}"
PIDFILE="${LANGSUITE_BOT_PIDFILE:-${LOG%.log}.pid}"
mkdir -p "$(dirname "$LOG")"
if [ -z "${LANGSUITE_TELEGRAM_TOKEN:-}" ]; then
  echo "$(date -Is) LANGSUITE_TELEGRAM_TOKEN is not set; not starting" >>"$LOG"; exit 4
fi
echo $$ >"$PIDFILE"
child=""
trap '[ -n "$child" ] && kill "$child" 2>/dev/null; rm -f "$PIDFILE"; exit 0' TERM INT
delay=2
while true; do
  start=$(date +%s)
  echo "$(date -Is) starting langsuite bot run" >>"$LOG"
  langsuite bot run >>"$LOG" 2>&1 &
  child=$!
  wait "$child"; code=$?
  echo "$(date -Is) bot exited with $code" >>"$LOG"
  [ "$code" -eq 4 ] && { rm -f "$PIDFILE"; exit 4; }  # bad or missing token: do not loop
  [ $(( $(date +%s) - start )) -gt 60 ] && delay=2 || delay=$(( delay < 60 ? delay * 2 : 60 ))
  sleep "$delay"
done
