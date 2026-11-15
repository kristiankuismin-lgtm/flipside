#!/bin/bash
# Keep harvesting until told to stop.
#
# harvest_all.py finishes a pass and exits with a summary, leaving most of
# the frontier unvisited - 243 entities read, 23,833 still queued. That is
# fine for a one-off but wrong for the night before a deadline, when the
# only thing standing between the graph we hold and the graph we want is
# wall-clock time against a rate limit.
#
# Each pass re-reads seeds.txt, so tiers that grew since the last pass are
# picked up. A pass that dies takes the pause and the next one starts.
cd "$(dirname "$0")" || exit 1
set -a; . ./.env; set +a

PASS=0
while [ ! -f harvest.stop ]; do
  PASS=$((PASS + 1))
  echo "=== pass $PASS  $(date '+%H:%M:%S') ===" >> harvest_loop.log
  CALA_CACHE_ONLY=1 .venv/bin/python harvest_seeds.py > seeds.txt 2>/dev/null
  CALA_MIN_INTERVAL=0.4 .venv/bin/python harvest_all.py \
      --max 4000 --workers 6 --seeds seeds.txt >> harvest_loop.log 2>&1
  sqlite3 cache.sqlite "select 'total ' || count(*) from harvest" >> harvest_loop.log
  sleep 5
done
echo "stopped at $(date '+%H:%M:%S')" >> harvest_loop.log
