#!/usr/bin/env bash
set -euo pipefail  # Stop on command errors or missing variables.
cd "$(dirname "$0")"

if [[ -e logs/development ]]; then
  echo "Development logs already exist. Inspect them before another paid run."
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "Create part_b/.env with both API keys before this paid run."
  exit 1
fi

uv run --locked python experiment.py --check
# Save the source files and inputs for this run.
mkdir -p logs/development
cp experiment.py schema.py pyproject.toml uv.lock rubric.md logs/development/
cp -R prompts logs/development/prompts
cp data/selected/development.json logs/development/cases.json
cp run_development.sh logs/development/
# Disable idle connection reuse. Keep certificate verification enabled.
export INSPECT_HTTP_POOL_KEEPALIVE_CONNECTIONS=0

# Run one target. Keep the same model settings and sample filter.
run_target() {
  local target_name="$1"
  local target_model="$2"
  uv run --locked --env-file .env inspect eval experiment.py@development \
    --model-role auditor=openai/gpt-5.6-luna \
    --model-role target="$target_model" \
    --model-role judge=openai/gpt-5.6-luna \
    -T max_replies=8 \
    --max-samples 2 --no-fail-on-error --retry-on-error 0 \
    --log-dir "logs/development/$target_name"
}

run_target mini openai/gpt-5-mini
run_target haiku anthropic/claude-haiku-4-5

echo "Inspect the sample errors and judge evidence before using these results."
