# Run Part A

Use Python 3.12 and uv. Run the commands below from `part_a/`.

## Setup

```bash
uv sync --locked
```

For paid evaluations, copy `.env.example` to `.env` and enter your `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. Do not commit `.env`.

## Inspect saved results

Open the saved logs in the Inspect viewer:

```bash
uv run --locked inspect view --log-dir logs
```

Logs include exploratory runs, completed evaluations, and failed attempts. The main analysis selects accepted samples from specific logs. It excludes A021, which used incorrect seed inputs, and samples with errors or credit failures.

Rebuild the summary from the saved logs without API calls:

```bash
uv run --locked python analysis/summarize_part_a.py
```

This writes `analysis/part_a_summary.json`. It contains per-scenario scores, source log paths, and aggregate comparisons. The primary comparison uses 170 shared scenarios.

Generate the figure from this summary without API calls:

```bash
uv run --locked python plot_results.py
```

This writes `../figures/part_a_dimensions.svg`.

## Run new evaluations

These commands make paid API calls. Each attempts all 173 default scenarios with an eight-turn auditor limit. They reproduce the final configuration, not the original sequence of batches and recovery attempts. New conversations and scores can differ from the saved results.

Use new output directories for each run to preserve the submitted logs.

### GPT-5 Mini

```bash
uv run --locked --env-file .env inspect eval inspect_petri/audit \
  --model-role auditor=openai/gpt-5.6-luna \
  --model-role target=openai/gpt-5-mini \
  --model-role judge=openai/gpt-5.6-luna \
  -T max_turns=8 \
  --max-samples 2 --no-fail-on-error --retry-on-error 0 \
  --log-dir logs/new_mini
```

### Claude Haiku 4.5

```bash
uv run --locked --env-file .env inspect eval inspect_petri/audit \
  --model-role auditor=openai/gpt-5.6-luna \
  --model-role target=anthropic/claude-haiku-4-5 \
  --model-role judge=openai/gpt-5.6-luna \
  -T max_turns=8 \
  --max-samples 2 --no-fail-on-error --retry-on-error 0 \
  --log-dir logs/new_haiku
```

The summary script selects the submitted logs by path. It does not automatically include these new output directories.

## Historical recovery code

- `rescore.py` exposes Petri's judge with additional output-format instructions for exploratory rescoring.
- `recover_cancelled_scores.py` prepares saved transcripts and exposes the default Petri judge for rescoring.
- `prepare_suite_recovery.py` selects recovery samples and verifies their seed inputs.
- `complete_suite_recovery.sh` runs the historical recovery sequence. It makes paid calls and stops if its output directories already exist.

These files document recovery of the original runs. They are not needed to inspect the saved results or generate the figure.

## Supporting files

| Files | Purpose |
| --- | --- |
| [analysis/A*_results.json](analysis/) | Per-run scores, errors, usage, and cost records. |
| [production_only_cost.json](analysis/production_only_cost.json) | Estimated cost of the samples selected for the final suite analysis. |
| [provisional_report_cost.json](analysis/provisional_report_cost.json) | Retained suite and exploratory cost subtotal, plus total historical spending. |
| [Haiku recovery IDs](analysis/suite_recovery_haiku_ids.txt), [Mini recovery IDs](analysis/suite_recovery_mini_ids.txt) | Sample IDs selected for the historical recovery runs. |
| [pyproject.toml](pyproject.toml), [uv.lock](uv.lock), [.python-version](.python-version) | Dependencies, locked package versions, and Python version. |
| [.env.example](.env.example), [root .gitignore](../.gitignore) | Credential template and files excluded from Git. |
| [PETRI_LICENSE](PETRI_LICENSE) | License for the Petri-derived code. |
