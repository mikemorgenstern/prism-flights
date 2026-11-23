#!/bin/sh
# Claude · 2026-11-23 · Session 8e680ddd · pre-publish privacy check (see tools/check_public.py for what it checks)
# Usage: sh tools/check_public.sh [--tree]     exit 0 = nothing private found; anything else = do not publish
exec python3 "$(dirname "$0")/check_public.py" "$@"
