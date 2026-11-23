#!/bin/sh
# Claude · 2026-11-23 · Session 8e680ddd · push only after the full privacy check passes, even if hooks are off
# Usage: sh tools/publish.sh [git push arguments]
set -e
sh "$(dirname "$0")/check_public.sh"
git push "$@"
