#!/usr/bin/env bash
# Usage: ./claude_curl.sh [file1.txt file2.txt]  (defaults: patient_2744.txt + questions file)
# Needs: ANTHROPIC_API_KEY, jq. Writes answer text to fable5.1_api.txt (raw response if no text came back).
set -euo pipefail
D="$(dirname "$0")"
F1="${1:-$D/patient_2744.txt}"; F2="${2:-$D/2744- Down Syndrome Questions.txt}"
PROMPT="$(cat "$D/prompt.txt")"
OUT="$D/fable5.1_api${SUFFIX:-}.txt"; RAW="$(mktemp)"

BODY=$(jq -n --rawfile f1 "$F1" --rawfile f2 "$F2" --arg p "$PROMPT" \
  --arg n1 "$(basename "$F1")" --arg n2 "$(basename "$F2")" '{
  model: "claude-fable-5-1",
  max_tokens: 128000,
  stream: true,
  output_config: {effort: "max"},
  fallbacks: "default",
  messages: [{role: "user", content: [
    {type: "document", title: $n1, source: {type: "text", media_type: "text/plain", data: $f1}},
    {type: "document", title: $n2, source: {type: "text", media_type: "text/plain", data: $f2}},
    {type: "text", text: $p}
  ]}]
}')

curl -sN https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "anthropic-beta: server-side-fallback-2026-07-01" \
  -H "content-type: application/json" \
  -d "$BODY" | tee "$RAW" | grep '^data: ' | sed 's/^data: //' \
  | jq -rj 'select(.delta.type? == "text_delta") | .delta.text' > "$OUT" || true

[ -s "$OUT" ] || cp "$RAW" "$OUT"
rm -f "$RAW"
echo "wrote $OUT"
