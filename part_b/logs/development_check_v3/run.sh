#!/usr/bin/env bash
set -euo pipefail  # Stop on command errors or missing variables.
cd "$(dirname "$0")"

# Select the run and protect its output directory.
case "${1:-}" in
  rescore)
    output=logs/development_rescore_v3
    entry=rescore.py
    ;;
  check)
    output=logs/development_check_v3
    entry=experiment.py
    ;;
  *)
    echo "Usage: bash run.sh {rescore|check}"
    echo "Both modes make paid API calls."
    exit 1
    ;;
esac
if [[ $# -ne 1 ]]; then
  echo "Supply exactly one mode: rescore or check."
  exit 1
fi
if [[ -e "$output" ]]; then
  echo "Logs already exist at $output. Inspect them before another paid run."
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "Create part_b/.env with the required API keys before this paid run."
  exit 1
fi

uv run --locked python "$entry" --check
# Save the source files and inputs for this run.
mkdir -p "$output"
cp experiment.py schema.py rescore.py rubric.md pyproject.toml uv.lock run.sh "$output/"
cp -R prompts "$output/prompts"
cp data/selected/development.json "$output/cases.json"
# Disable idle connection reuse. Keep certificate verification enabled.
export INSPECT_HTTP_POOL_KEEPALIVE_CONNECTIONS=0

if [[ "$1" == rescore ]]; then
  uv run --locked --env-file .env inspect eval rescore.py@rescore_saved \
    --model none \
    --model-role judge=openai/gpt-5.6-luna \
    --max-samples 2 --no-fail-on-error --retry-on-error 0 \
    --log-dir "$output"
  exit 0
fi

# Run one target. Keep the same model settings and sample filter.
run_target() {
  local target_name="$1"
  local target_model="$2"
  uv run --locked --env-file .env inspect eval experiment.py@development \
    --model-role auditor=openai/gpt-5.6-luna \
    --model-role "target={model: $target_model, max_tokens: 4096, max_retries: 0, timeout: 180}" \
    --model-role judge=openai/gpt-5.6-luna \
    --sample-id dev_02_ordinary,dev_02_direct \
    -T max_replies=8 \
    --max-samples 2 --no-fail-on-error --retry-on-error 0 \
    --log-dir "$output/$target_name"
}

run_target mini openai/gpt-5-mini
run_target haiku anthropic/claude-haiku-4-5
