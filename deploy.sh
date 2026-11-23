#!/bin/bash
# Claude · 2026-11-22 · Session 8e680ddd · build the portal pages and publish them to the server named in config.local.json.
# Usage: bash deploy.sh             pages only
#        bash deploy.sh --service   also copy the service, its helpers and config.local.json, then restart the service
# Needs in config.local.json: box (ssh target), box_project (folder there, relative to that login's home) and
# public_base (address the pages are checked at). The service runs there as the systemd user unit flights-portal.
# Always builds from data/ into site/ here, whatever FLIGHTS_DATA or FLIGHTS_SITE say in the shell.
set -euo pipefail
cd "$(dirname "$0")"
cfg() { python3 -c 'import sys; sys.path.insert(0, "src"); import portal_config as c; print(c.get(sys.argv[1], ""))' "$1"; }
BOX=$(cfg box); DEST=$(cfg box_project); BASE=$(cfg public_base)
if [ -z "$BOX" ] || [ -z "$DEST" ]; then
  echo "deploy.sh: set box and box_project in config.local.json (see config.example.json); nothing was published" >&2; exit 1
fi
FLIGHTS_DATA=data FLIGHTS_SITE=site python3 src/build_portal.py
rsync -a --delete site/ "$BOX:$DEST/site/"
if [ "${1:-}" = "--service" ]; then
  scp -q src/service.py src/ask_helper.py src/jobs_start.py src/portal_config.py "$BOX:$DEST/src/"
  scp -q config.local.json "$BOX:$DEST/config.local.json"
  ssh "$BOX" 'systemctl --user restart flights-portal && sleep 1 && systemctl --user is-active flights-portal'
fi
if [ -n "$BASE" ]; then
  for u in /flights/ $(cd site && ls -d */ | sed 's#^#/flights/#'); do
    printf '%s %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "$BASE$u")" "$BASE$u"
  done
fi
