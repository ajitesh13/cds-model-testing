#!/usr/bin/env bash
# Usage: ./gemini_curl.sh [file1.txt file2.txt]  (defaults: patient_2744.txt + questions file)
# Needs: gcloud auth (application-default), jq, GOOGLE_CLOUD_PROJECT or THALAMUS_VERTEX_PROJECT_ID.
# Writes answer text to gemini3.1pro_api.txt (raw response if no text came back).
set -euo pipefail
D="$(dirname "$0")"
F1="${1:-$D/patient_2744.txt}"; F2="${2:-$D/2744- Down Syndrome Questions.txt}"
PROMPT="$(cat "$D/prompt.txt")"
OUT="$D/gemini3.1pro_api${SUFFIX:-}.txt"; RAW="$(mktemp)"
PROJECT="${THALAMUS_VERTEX_PROJECT_ID:-${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}}"
LOCATION="${THALAMUS_GEMINI_REGION:-global}"
MODEL="gemini-3.1-pro-preview"
HOST="aiplatform.googleapis.com"; [ "$LOCATION" != "global" ] && HOST="$LOCATION-aiplatform.googleapis.com"

BODY=$(jq -n --rawfile f1 "$F1" --rawfile f2 "$F2" --arg p "$PROMPT" \
  --arg n1 "$(basename "$F1")" --arg n2 "$(basename "$F2")" '{
  contents: [{role: "user", parts: [
    {text: ("=== " + $n1 + " ===\n" + $f1)},
    {text: ("=== " + $n2 + " ===\n" + $f2)},
    {text: $p}
  ]}],
  generationConfig: {maxOutputTokens: 65536, thinkingConfig: {thinkingLevel: "HIGH"}}
}')

curl -sN "https://$HOST/v1/projects/$PROJECT/locations/$LOCATION/publishers/google/models/$MODEL:streamGenerateContent?alt=sse" \
  -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" \
  -H "content-type: application/json" \
  -d "$BODY" | tee "$RAW" | grep '^data: ' | sed 's/^data: //' \
  | jq -rj '.candidates[0].content.parts[]? | select(.thought != true) | .text // empty' > "$OUT" || true

[ -s "$OUT" ] || cp "$RAW" "$OUT"
rm -f "$RAW"
echo "wrote $OUT"
