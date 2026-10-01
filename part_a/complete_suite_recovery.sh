#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

for output in logs/suite_recovery_haiku_verified logs/suite_recovery_mini_verified logs/suite_recovery_judges_verified; do
  if [ -e "$output" ]; then
    echo "Recovery output already exists: $output. Inspect it before another paid run."
    exit 1
  fi
done

uv run python prepare_suite_recovery.py
export INSPECT_HTTP_POOL_KEEPALIVE_CONNECTIONS=0

uv run inspect eval inspect_petri/audit \
  --model-role auditor=openai/gpt-5.6-luna \
  --model-role target=anthropic/claude-haiku-4-5 \
  --model-role judge=openai/gpt-5.6-luna \
  --sample-id "$(cat analysis/suite_recovery_haiku_ids.txt)" \
  -T max_turns=8 --max-samples 2 --no-fail-on-error --retry-on-error 0 \
  --log-dir logs/suite_recovery_haiku_verified

uv run inspect eval inspect_petri/audit \
  --model-role auditor=openai/gpt-5.6-luna \
  --model-role target=openai/gpt-5-mini \
  --model-role judge=openai/gpt-5.6-luna \
  --sample-id "$(cat analysis/suite_recovery_mini_ids.txt)" \
  -T max_turns=8 --max-samples 2 --no-fail-on-error --retry-on-error 0 \
  --log-dir logs/suite_recovery_mini_verified

mkdir -p logs/suite_recovery_judges_verified
for target in haiku mini; do
  uv run inspect score "analysis/suite_recovery_${target}_judge_input.eval" \
    --scorer recover_cancelled_scores.py@default_petri_judge \
    --model-role judge=openai/gpt-5.6-luna \
    --action overwrite \
    --output-file "logs/suite_recovery_judges_verified/${target}.eval"
done
