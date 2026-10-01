"""Score four saved development conversations with the current judge instructions.

No tutor, student, or stop-check calls occur. Old scores are not given to the judge.
Run with --check to inspect inputs without any model calls.
"""
import copy
import hashlib
import json

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.model import GenerateConfig
from inspect_ai.solver import solver
from inspect_ai.util import json_schema

from experiment import BASE, PROTOCOL_VERSION, feedback_judge, read_text
from schema import assessment_response_model


SOURCE_DIRECTORY = BASE / "logs/development_check_v3"
EXPECTED_SAMPLES = {"dev_02_ordinary", "dev_02_direct"}


def check_saved_conversation(saved, current_case):
    """Reject incomplete conversations or changes to the original assignment."""
    if not saved.get("conversation_complete"):
        raise ValueError("A source conversation is incomplete. Inspect it before rescoring.")

    # Annotations may change. The assignment, answer, and transcript must not.
    for field in ("code", "input_assumptions", "assignment", "student_response", "reference_answer"):
        if current_case[field] != saved["case"][field]:
            raise ValueError("The source case differs from the current case beyond its annotations.")

    conversation = saved["conversation"]
    if not conversation or len(conversation) % 2:
        raise ValueError("The saved conversation must end with a tutor reply.")
    for index, message in enumerate(conversation):
        expected_role = "student" if index % 2 == 0 else "tutor"
        if message["id"] != f"M{index + 1}" or message["role"] != expected_role or not message["text"].strip():
            raise ValueError("The saved conversation has invalid message IDs, roles, or text.")


def load_saved_samples():
    """Read two saved conversations per target and prepare new judge inputs."""
    cases = {case["case_id"]: case for case in json.loads(read_text("data/development.json"))}
    judge_prompt = read_text("prompts/judge.md")
    rubric = read_text("rubric.md")
    samples = []
    for target_name in ("mini", "haiku"):
        paths = sorted((SOURCE_DIRECTORY / target_name).glob("*.eval"))
        if len(paths) != 1:
            raise ValueError("Each target needs exactly one version 0.3 check log.")
        path = paths[0]
        log = read_eval_log(path)
        if len(log.samples or []) != 2 or {s.id for s in log.samples} != EXPECTED_SAMPLES:
            raise ValueError("The source log does not contain the two expected samples.")
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        for saved in log.samples:
            old = saved.metadata
            case = copy.deepcopy(cases[old["case"]["case_id"]])
            check_saved_conversation(old, case)
            conversation = copy.deepcopy(old["conversation"])
            samples.append(Sample(
                id=f"{target_name}_{saved.id}",
                input="Score the saved conversation. Do not generate a new conversation.",
                metadata={
                    # The judge receives the saved conversation and current scoring instructions.
                    "case": case,
                    "conversation": conversation,
                    "conversation_complete": True,
                    "tutor_prompt": old["tutor_prompt"],
                    "judge_prompt": judge_prompt,
                    "rubric": rubric,
                    # These fields document the source. They are not sent to the judge.
                    "condition": old["condition"],
                    "target_name": target_name,
                    "stop_reason": old["stop_reason"],
                    "source_log": str(path.relative_to(BASE)),
                    "source_log_sha256": source_hash,
                    "source_sample_id": saved.id,
                    "source_sample_uuid": saved.uuid,
                    "original_annotations": old["case"]["answer_annotations"],
                    "judge_protocol_version": PROTOCOL_VERSION,
                    "transcript_sha256": hashlib.sha256(json.dumps(conversation, sort_keys=True).encode()).hexdigest(),
                },
            ))
    return samples


@solver
def saved_conversation():
    # Inspect requires a solver. This one returns the saved state without generating text.
    async def solve(state, generate):
        return state

    return solve


@task
def rescore_saved():
    # feedback_judge is the only part of this task that calls a model.
    return Task(
        dataset=load_saved_samples(),
        solver=saved_conversation(),
        scorer=feedback_judge(),
        config=GenerateConfig(max_retries=0, timeout=180, fail_on_refusal=True),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check saved rescore inputs without model calls.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    # Loading files and building response schemas do not call a model.
    for sample in load_saved_samples():
        tutor_ids = [m["id"] for m in sample.metadata["conversation"] if m["role"] == "tutor"]
        json_schema(assessment_response_model(tutor_ids))
        print(sample.id)
    print("Four saved conversations. No model calls were made.")
