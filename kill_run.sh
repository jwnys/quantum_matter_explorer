#!/usr/bin/env bash
# kill_run.sh: kill all processes belonging to one run, by run id.
#
# A run is a `main.py` process plus its children: the vLLM server and the Julia
# workers. Those children are spawned into their own process groups, so a plain
# `kill -- -<pgid>` misses them. This script finds the run's main.py by its
# working directory and open files, then kills it and every descendant, and
# nothing else (other runs are never touched).
#
# Usage:
#   ./kill_run.sh <run-id>        e.g. ./kill_run.sh run_20260629_161328
#   ./kill_run.sh 161328          any substring of the run-dir name works
#   ./kill_run.sh -n <run-id>     DRY RUN: show what would be killed, kill nothing
set -u

DRY=0
[ "${1:-}" = "-n" ] && { DRY=1; shift; }
RUNID="${1:-}"
[ -z "$RUNID" ] && { echo "usage: $0 [-n] <run-id|substring>"; exit 2; }

# 1. main.py process(es) whose cwd or open files reference this run.
mapfile -t mains < <(
  for pid in $(pgrep -f 'main\.py' 2>/dev/null); do
    if ls -l "/proc/$pid/cwd" "/proc/$pid/fd" 2>/dev/null | grep -q -- "$RUNID"; then
      echo "$pid"
    fi
  done
)
if [ "${#mains[@]}" -eq 0 ]; then
  echo "No running main.py found for '$RUNID', nothing to kill."
  exit 0
fi

# 2. main PID(s) + all descendants (vLLM server + its workers, Julia workers, ...).
descendants() { local p=$1; echo "$p"; local c
  for c in $(pgrep -P "$p" 2>/dev/null); do descendants "$c"; done; }
mapfile -t pids < <(for m in "${mains[@]}"; do descendants "$m"; done | sort -un)

echo "Run '$RUNID' -> ${#pids[@]} process(es):"
ps -o pid,ppid,etime,cmd -p "$(IFS=,; echo "${pids[*]}")" 2>/dev/null | cut -c1-118
echo

if [ "$DRY" -eq 1 ]; then echo "(dry run, nothing killed)"; exit 0; fi

# 3. graceful TERM, wait briefly, then SIGKILL any stragglers (vLLM can be slow).
kill -TERM "${pids[@]}" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8; do
  left=$(for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && echo x; done | wc -l)
  [ "$left" -eq 0 ] && break
  sleep 1
done
for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null || true; done

# 4. report
left=$(for p in "${pids[@]}"; do kill -0 "$p" 2>/dev/null && echo "$p"; done | tr '\n' ' ')
if [ -z "$left" ]; then echo "Killed run '$RUNID' cleanly."
else echo "WARNING: still alive: $left"; fi
