# Run Part B

Use Python 3.12 and uv. Run these commands from `part_b/`.

## Setup

```bash
uv sync --locked
```

For paid runs, create `.env` here with `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`. Do not commit this file. The selected dataset is included in `data/development.json` and `data/evaluation.json`.

## Check inputs without API calls

```bash
uv run --locked python experiment.py --check --split evaluation
```

Use `--split development` to check development inputs.

## Read saved results

Read the [saved summary](analysis/evaluation_summary.json), or open the saved conversations:

```bash
uv run --locked inspect view --log-dir logs/evaluation
```

Rebuild the summary from the saved logs without API calls:

```bash
uv run --locked python analysis/summarize_evaluation.py
```

This writes `analysis/evaluation_summary.json`. It does not change logs or reports.

## Paid runs

| Command | Work |
| --- | --- |
| `bash run.sh check` | Run 12 development conversations. |
| `bash run.sh evaluation` | Run 120 evaluation conversations. |
| `bash run.sh rescore` | Judge four saved development conversations again. |

Each command stops if its output directory already exists. Before a new run, set a new `output` directory in the matching mode in `run.sh`. Keep existing logs. Rescore does not recover failed evaluation judgments.

## Supporting files

| Files | Purpose |
| --- | --- |
| [experiment.py](experiment.py), [run.sh](run.sh) | Define the experiment and run each paid mode. |
| [schema.py](schema.py) | Define and validate judge responses, then summarize scores and disclosure timing. |
| [rescore.py](rescore.py) | Prepare four saved development conversations for new judge calls. |
| [plot_results.py](plot_results.py) | Generate `../figures/part_b_disclosure.svg` from the saved summary without API calls. |
| [summarize_evaluation.py](analysis/summarize_evaluation.py) | Rebuild the summary from saved evaluation logs without API calls. |
| [prompts/](prompts/), [rubric.md](rubric.md) | Tutor, student auditor, stop-check, opening, and judge instructions, plus scoring criteria. |
| [data/](data/) | Development and evaluation cases with reference answers and annotations. |
| [logs/](logs/) | Saved conversations and historical copies of code, prompts, cases, and dependency files used for each run. |
| [pyproject.toml](pyproject.toml), [uv.lock](uv.lock), [.python-version](.python-version) | Dependencies, locked package versions, and Python version. |
| [.env.example](.env.example), [root .gitignore](../.gitignore) | Credential template and files excluded from Git. |
