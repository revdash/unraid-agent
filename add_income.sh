#!/bin/bash
# add_income.sh -- posts one manual income entry to Revdash.
#
# This exists so the agent can be told "add $X from Y" in plain
# English and have it land on the dashboard, WITHOUT giving the LLM
# raw curl access (which could hit arbitrary hosts, read/write local
# files via curl's own flags, etc). This script only ever does one
# thing: POST a validated amount + name to a fixed local URL.
#
# Usage: ./add_income.sh "Source Name" AMOUNT [source_type] [entry_date]
#   source_type defaults to "other", entry_date defaults to today.

set -e

DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:8420}"

SOURCE_NAME="$1"
AMOUNT="$2"
SOURCE_TYPE="${3:-other}"
ENTRY_DATE="${4:-$(date -u +%Y-%m-%d)}"

if [ -z "$SOURCE_NAME" ] || [ -z "$AMOUNT" ]; then
  echo "Usage: $0 \"Source Name\" AMOUNT [source_type] [entry_date]"
  exit 1
fi

# Reject anything that isn't a plain positive/negative decimal number --
# this value goes straight into a JSON body, so it must not be able to
# carry injected JSON/script content.
if ! [[ "$AMOUNT" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; then
  echo "[error] AMOUNT must be a plain number, got: $AMOUNT"
  exit 1
fi

case "$SOURCE_TYPE" in
  app|website|service|other) ;;
  *)
    echo "[error] source_type must be one of: app, website, service, other"
    exit 1
    ;;
esac

if ! [[ "$ENTRY_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "[error] entry_date must be YYYY-MM-DD, got: $ENTRY_DATE"
  exit 1
fi

# Escape double-quotes and backslashes in the name so it can't break
# out of the JSON string it's placed into.
ESCAPED_NAME=$(printf '%s' "$SOURCE_NAME" | sed 's/\\/\\\\/g; s/"/\\"/g')

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$DASHBOARD_URL/api/income" \
  -H "Content-Type: application/json" \
  -d "{\"source_name\":\"$ESCAPED_NAME\",\"source_type\":\"$SOURCE_TYPE\",\"amount\":$AMOUNT,\"entry_date\":\"$ENTRY_DATE\",\"platform\":\"manual\",\"note\":\"Added via agent\"}")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
  echo "[ok] Logged \$$AMOUNT for '$SOURCE_NAME' on $ENTRY_DATE"
else
  echo "[error] Dashboard returned HTTP $HTTP_CODE: $BODY"
  exit 1
fi
