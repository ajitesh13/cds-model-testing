#!/usr/bin/env bash
# Usage: ./openai_curl.sh [file1.txt file2.txt]  (defaults: patient_2744.txt + questions file)
# Needs: OPENAI_API_KEY, jq. Writes answer text to gpt6_astra_api.txt (raw response if no text came back).
# Overrides: OPENAI_MODEL (default "gpt-6-astra"), OPENAI_EFFORT (default "max"), OPENAI_MAX_OUTPUT (default 128000).
set -euo pipefail
D="$(dirname "$0")"
F1="${1:-$D/patient_2744.txt}"; F2="${2:-$D/2744- Down Syndrome Questions.txt}"
PROMPT="$(cat "$D/prompt.txt")"
OUT="$D/gpt6_astra_api${SUFFIX:-}.txt"; RAW="$(mktemp)"
MODEL="${OPENAI_MODEL:-gpt-6-astra}"; EFFORT="${OPENAI_EFFORT:-max}"; MAXOUT="${OPENAI_MAX_OUTPUT:-128000}"

BODY=$(jq -n --rawfile f1 "$F1" --rawfile f2 "$F2" --arg p "$PROMPT" \
  --arg n1 "$(basename "$F1")" --arg n2 "$(basename "$F2")" \
  --arg m "$MODEL" --arg e "$EFFORT" --argjson mx "$MAXOUT" '{
  model: $m,
  stream: true,
  max_output_tokens: $mx,
  reasoning: {effort: $e},
  input: [{role: "user", content: [
    {type: "input_text", text: ("=== " + $n1 + " ===\n" + $f1)},
    {type: "input_text", text: ("=== " + $n2 + " ===\n" + $f2)},
    {type: "input_text", text: $p}
  ]}]
}')

curl -sN https://api.openai.com/v1/responses \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "content-type: application/json" \
  -d "$BODY" | tee "$RAW" | grep '^data: ' | sed 's/^data: //' \
  | jq -rj 'select(.type? == "response.output_text.delta") | .delta' > "$OUT" || true

[ -s "$OUT" ] || cp "$RAW" "$OUT"
rm -f "$RAW"
echo "wrote $OUT"
