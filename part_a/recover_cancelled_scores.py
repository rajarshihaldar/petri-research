from pathlib import Path

from inspect_ai.log import read_eval_log, write_eval_log
from inspect_ai.scorer import Scorer, mean, scorer, stderr
from inspect_petri import audit_judge
from inspect_scout import as_scorer


@scorer(metrics={"*": [mean(), stderr()]})
def default_petri_judge() -> Scorer:
    return as_scorer(audit_judge())


def prepare() -> None:
    root = Path(__file__).resolve().parent
    source = root / "logs/part_a_luna_luna_haiku45_002_011/2026-09-22T21-21-29-00-00_audit_5WdaKhZmJD63jGXtuvvqDE.eval"
    destination = root / "logs/recovery_haiku45_002_011/completed_audits.eval"
    selected = {"antipsychotic_discontinuation", "ai_rights_employee_bold_tools"}
    if destination.exists():
        raise FileExistsError("The recovery input already exists. Inspect it before reuse.")
    log = read_eval_log(source)
    samples = [s for s in log.samples or [] if s.id in selected]
    if len(samples) != 2 or {s.id for s in samples} != selected:
        raise ValueError("The log must contain both selected samples exactly once.")
    for sample in samples:
        if sample.scores or sample.error is None:
            raise ValueError("Each selected sample must be unscored and cancelled.")
        if "CancelledError" not in sample.error.message:
            raise ValueError("The sample error is not a cancellation.")
        judge_events = [e for e in sample.events if getattr(e, "event", None) == "model" and getattr(e, "role", None) == "judge"]
        if not judge_events or not sample.timelines:
            raise ValueError("The completed audit must have a timeline and a judge event.")
        sample.metadata = dict(sample.metadata or {})
        sample.metadata["recovery_source"] = str(source)
        sample.metadata["original_scoring_error"] = sample.error.model_dump(mode="json")
        sample.error = None
    log.samples = samples
    log.eval.dataset.samples = len(samples)
    log.eval.dataset.sample_ids = [s.id for s in samples]
    log.eval.config.limit = None
    log.results = None
    log.reductions = None
    log.eval.metadata = dict(log.eval.metadata or {})
    log.eval.metadata["recovery_source"] = str(source)
    log.eval.metadata["recovery_note"] = "Only two completed audits are included. Original events and usage are retained. Judge scores are pending. Header statistics describe the source run."
    log.error = None
    log.status = "started"
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_eval_log(log, destination)
    print(destination)


if __name__ == "__main__":
    prepare()
