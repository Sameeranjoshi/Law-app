#!/usr/bin/env bash
# sync.sh — pull today's cause list (and optionally your matters) from eCourts
# via bharat-courts, into ./exports/ so you can upload them in the office app
# (eCourts tab → Import from bharat-courts).
#
# NOTE: bharat-courts runs the eCourts scraping/CAPTCHA on THIS machine, run by you.
# Fill in your court codes once below (find them with the discovery commands in README.md).
#
# Usage:
#   ./sync.sh                 # today's cause list only
#   ./sync.sh "Joshi"         # cause list + rebuild portfolio by party/surname
#   ./sync.sh "Joshi" 2024    # ... for a specific filing year
set -euo pipefail

# ---- your court (Maharashtra = state 27) — fill these in once ----
STATE=27
DIST=""        # Ahmednagar district code  →  bharat-courts districtcourts districts --state 27
COMPLEX=""     # court complex code         →  bharat-courts districtcourts complexes --state 27 --dist "$DIST"
EST=""         # establishment code         →  bharat-courts districtcourts establishments --state 27 --dist "$DIST" --complex "$COMPLEX"
COURT_NO=""    # cause-list court, e.g. 1@2 →  bharat-courts districtcourts courts --state 27 --dist "$DIST" --complex "$COMPLEX" --est "$EST"

PARTY="${1:-}"
YEAR="${2:-$(date +%Y)}"
OUT="./exports"
TODAY="$(date +%d-%m-%Y)"
STAMP="$(date +%Y%m%d)"

if [ -z "$DIST" ] || [ -z "$COMPLEX" ] || [ -z "$EST" ] || [ -z "$COURT_NO" ]; then
  echo "Fill in DIST / COMPLEX / EST / COURT_NO at the top of sync.sh first." >&2
  echo "Discover them with: bharat-courts districtcourts districts --state 27" >&2
  exit 1
fi

mkdir -p "$OUT"

echo "→ Today's cause list ($TODAY) ..."
bharat-courts --json districtcourts cause-list \
  --state "$STATE" --dist "$DIST" --complex "$COMPLEX" --est "$EST" \
  --court-no "$COURT_NO" --date "$TODAY" > "$OUT/causelist-$STAMP.json"

if [ -n "$PARTY" ]; then
  echo "→ Matters for party '$PARTY' ($YEAR) ..."
  bharat-courts --json districtcourts search-by-party \
    --state "$STATE" --dist "$DIST" --complex "$COMPLEX" --est "$EST" \
    --party "$PARTY" --year "$YEAR" > "$OUT/cases-$STAMP.json"
fi

echo "Done. Files written to $OUT/ :"
ls -1 "$OUT"
echo "Now open the office app → eCourts → Import from bharat-courts, and upload them."
