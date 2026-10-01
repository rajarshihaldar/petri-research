#!/usr/bin/env bash
set -euo pipefail  # Stop on command errors or missing variables.
cd "$(dirname "$0")"
split=development

# 1. Choose the dataset and a separate output directory.
case "${1:-}" in
  rescore)
    output=logs/development_rescore_v4
    ;;
  check)
    output=logs/development_full_v4
    ;;
  evaluation)
    output=logs/evaluation
    split=evaluation
    ;;
  *)
    echo "Usage: bash run.sh {rescore|check|evaluation}"
    echo "All modes make paid API calls."
    exit 1
    ;;
esac
if [[ $# -ne 1 ]]; then
  echo "Supply exactly one mode: rescore, check, or evaluation."
  exit 1
fi
# 2. Protect old results and require local API credentials.
if [[ -e "$output" ]]; then
  echo "Logs already exist at $output. Inspect them before another paid run."
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "Create part_b/.env with the required API keys before this paid run."
  exit 1
fi

# 3. Check inputs without model calls, then save the files used for this run.
if [[ "$1" == rescore ]]; then
  uv run --locked python rescore.py --check
else
  uv run --locked python experiment.py --check --split "$split"
fi
mkdir -p "$output"
cp experiment.py schema.py rescore.py rubric.md pyproject.toml uv.lock run.sh "$output/"
cp -R prompts "$output/prompts"
cp "data/$split.json" "$output/cases.json"
# This avoids idle connection reuse. Certificate verification remains enabled.
export INSPECT_HTTP_POOL_KEEPALIVE_CONNECTIONS=0

# 4. Rescoring calls only the judge, then exits.
if [[ "$1" == rescore ]]; then
  uv run --locked --env-file .env inspect eval rescore.py@rescore_saved \
    --model none \
    --model-role judge=openai/gpt-5.6-luna \
    --max-samples 2 --no-fail-on-error --retry-on-error 0 \
    --log-dir "$output"
  exit 0
fi

# 5. Run the same experiment once per target. Luna also handles stop checks.
run_target() {
  local target_name="$1"
  local target_model="$2"
  # Two concurrent samples. Record sample failures and continue without retries.
  uv run --locked --env-file .env inspect eval "experiment.py@$split" \
    --model-role auditor=openai/gpt-5.6-luna \
    --model-role "target={model: $target_model, max_tokens: 4096, max_retries: 0, timeout: 180}" \
    --model-role judge=openai/gpt-5.6-luna \
    -T max_replies=8 \
    --max-samples 2 --no-fail-on-error --retry-on-error 0 \
    --log-dir "$output/$target_name"
}

run_target mini openai/gpt-5-mini
run_target haiku anthropic/claude-haiku-4-5
