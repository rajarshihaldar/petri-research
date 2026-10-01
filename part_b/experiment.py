"""Run one question under one student condition.

Call order: tutor -> stop checker -> student -> tutor, then judge once.
The opening student message is fixed text, not a model call.
The stop checker and student use separate calls to the auditor model.
Only the judge receives private answer annotations.
"""
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from inspect_ai import Task, task
from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, GenerateConfig, ResponseSchema, get_model
from inspect_ai.scorer import Score, Scorer, Target, mean, scorer
from inspect_ai.solver import TaskState, solver
from inspect_ai.util import json_schema
from inspect_petri import audit_solver, target_agent
from inspect_petri.target import ResponseOutput, controller

from schema import (
    Assessment, assessment_response_model,
    disclosure_timing, set_initial_adaptation, summarize_assessment,
    validate_assessment,
)


# These two response forms belong to conversation control, not judging.
class StudentStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str


class StopDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stop_reason: Literal["continue", "confirmed_answer", "final_refusal"]
    evidence_message_id: str | None
    reason: str


BASE = Path(__file__).parent
CONDITIONS = {
    "ordinary": "Ordinary feedback",
    "direct": "Direct answer pressure",
    "gradual": "Gradual answer requests",
}
PUBLIC_FIELDS = ("assignment", "input_assumptions", "code", "student_response")
PROTOCOL_VERSION = "0.4"


def read_text(relative):
    return (BASE / relative).read_text().strip()


def render_opening(case, template):
    for field in PUBLIC_FIELDS:
        template = template.replace("{{" + field + "}}", case[field])
    if "{{" in template:
        raise ValueError("The opening message has an unresolved placeholder.")
    return template


def auditor_prompt(text, heading):
    """Keep the shared instructions and exactly one condition."""
    shared, *sections = text.split("\n## ")
    for section in sections:
        title, body = section.split("\n", 1)
        if title.strip() == heading:
            return shared + "\n\n## " + title + "\n" + body
    raise ValueError("The requested auditor condition is missing.")


def load_samples(max_replies, split="development"):
    """Create one sample for each question and condition."""
    if not 2 <= max_replies <= 8:
        raise ValueError("The experiment requires between 2 and 8 tutor replies.")
    expected_count = {"development": 2, "evaluation": 20}[split]
    cases = json.loads(read_text(f"data/{split}.json"))
    if len(cases) != expected_count or len({case["case_id"] for case in cases}) != expected_count:
        raise ValueError("The dataset has an incorrect case count or duplicate case IDs.")
    texts = {name: read_text(f"prompts/{name}.md") for name in ("tutor", "auditor", "stop", "opening", "judge")}
    texts["rubric"] = read_text("rubric.md")
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in texts.items()}
    samples = []
    for case in cases:
        annotations = case.get("answer_annotations", {})
        if case["split"] != split or not annotations.get("required_components"):
            raise ValueError("Each case must match the requested split and have answer annotations.")
        component_ids = [item["id"] for item in annotations["required_components"]]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("Answer component IDs must be unique within a case.")
        opening = render_opening(case, texts["opening"])
        for condition, heading in CONDITIONS.items():
            samples.append(Sample(
                id=f"{case['case_id']}_{condition}",
                input=opening,
                metadata={
                    "case": case,
                    "condition": condition,
                    "opening": opening,
                    "tutor_prompt": texts["tutor"],
                    "auditor_prompt": auditor_prompt(texts["auditor"], heading),
                    "stop_prompt": texts["stop"],
                    "judge_prompt": texts["judge"],
                    "rubric": texts["rubric"],
                    "prompt_hashes": hashes,
                    "max_replies": max_replies,
                    "protocol_version": PROTOCOL_VERSION,
                },
            ))
    return samples


def require_text(output):
    if not output.choices or output.choices[0].stop_reason != "stop":
        raise ValueError("The model response did not finish normally. Inspect the saved event.")
    if output.message.tool_calls or not output.message.text.strip():
        raise ValueError("The model must return nonempty text without tool calls.")
    return output.message.text


async def generate_student_message(state, prompt, conversation):
    """Make one auditor call to write the next student message."""
    request = ChatMessageUser(content=json.dumps({"conversation": conversation}, ensure_ascii=False))
    auditor = get_model(role="auditor", required=True)
    output = await auditor.generate(
        input=[ChatMessageSystem(content=prompt), request],
        config=GenerateConfig(
            max_tokens=2048,
            response_schema=ResponseSchema(
                name="student_step", json_schema=json_schema(StudentStep), strict=True,
            ),
        ),
        cache=False,
    )
    # This history is for logging. It is not sent to the tutor.
    state.messages.extend([request, output.message])
    state.output = output
    student = StudentStep.model_validate_json(require_text(output))
    if not student.message.strip():
        raise ValueError("A continuation needs a nonempty student message.")
    return student.message


async def check_stop_with_model(state, prompt, conversation):
    """Make a separate auditor call to decide whether to stop."""
    # This is a custom model call, not a Petri stop flag.
    # It receives no student condition, reference answer, or annotations.
    request = ChatMessageUser(content=json.dumps({"conversation": conversation}, ensure_ascii=False))
    stop_model = get_model(role="auditor", required=True)
    output = await stop_model.generate(
        input=[ChatMessageSystem(content=prompt), request],
        config=GenerateConfig(
            max_tokens=2048,
            response_schema=ResponseSchema(
                name="stop_decision", json_schema=json_schema(StopDecision), strict=True,
            ),
        ),
        cache=False,
    )
    state.messages.extend([request, output.message])
    state.output = output
    decision = StopDecision.model_validate_json(require_text(output))
    if not decision.reason.strip():
        raise ValueError("A stop decision needs a reason.")
    if decision.stop_reason == "continue":
        if decision.evidence_message_id is not None:
            raise ValueError("A continuation decision needs a null evidence ID.")
    elif decision.evidence_message_id != conversation[-1]["id"]:
        raise ValueError("A stop decision must cite the latest tutor message.")
    return decision


@agent
def student_driver() -> Agent:
    # Inspect requires an agent factory that returns an async function.
    async def execute(state: AgentState) -> AgentState:
        # Petri controls the target. Metadata holds our readable transcript.
        ctrl = controller()
        metadata = ctrl.state.metadata
        conversation = []
        metadata["conversation"] = conversation
        metadata["conversation_complete"] = False
        metadata["stop_reason"] = "incomplete"
        metadata["stop_decisions"] = []
        await ctrl.stage_system(metadata["tutor_prompt"])
        student_message = metadata["opening"]
        state.messages[:] = []

        for reply in range(metadata["max_replies"]):
            # Send the student message and get one tutor reply through Petri.
            await ctrl.stage_user(student_message)
            conversation.append({"id": f"M{len(conversation) + 1}", "role": "student", "text": student_message})
            response = await ctrl.resume(expected=ResponseOutput)
            conversation.append({"id": f"M{len(conversation) + 1}", "role": "tutor", "text": require_text(response.output)})

            # The reply limit takes priority over another stop-check call.
            if reply + 1 == metadata["max_replies"]:
                metadata["stop_reason"] = "reply_limit"
                break
            # Separate paid call: decide whether to stop before writing more text.
            decision = await check_stop_with_model(state, metadata["stop_prompt"], conversation)
            metadata["stop_decisions"].append({
                "after_message_id": conversation[-1]["id"],
                **decision.model_dump(),
            })
            if decision.stop_reason != "continue":
                metadata["stop_reason"] = decision.stop_reason
                metadata["stop_evidence_message_id"] = decision.evidence_message_id
                break

            # Separate paid call: write the next student message for this condition.
            student_message = await generate_student_message(
                state, metadata["auditor_prompt"], conversation,
            )

        metadata["conversation_complete"] = True
        return state

    return execute


@scorer(metrics={"boundary_compliance": [mean()]})
def feedback_judge() -> Scorer:
    # Inspect calls this scorer once after the conversation finishes.
    async def score(state: TaskState, target: Target) -> Score:
        metadata = state.metadata
        if not metadata.get("conversation_complete"):
            raise ValueError("Do not score an incomplete conversation.")
        case = metadata["case"]
        # Only the judge receives the reference answer and private annotations.
        case_fields = (*PUBLIC_FIELDS, "reference_answer", "misconception", "answer_annotations")
        payload = {
            "case": {field: case[field] for field in case_fields},
            "tutor_instructions": metadata["tutor_prompt"],
            "conversation": metadata["conversation"],
            "expected_tutor_message_ids": [
                message["id"] for message in metadata["conversation"] if message["role"] == "tutor"
            ],
        }
        # Require one response field per tutor message so none can be omitted.
        response_model = assessment_response_model(payload["expected_tutor_message_ids"])
        output = await get_model(role="judge", required=True).generate(
            input=[
                ChatMessageSystem(content=metadata["judge_prompt"] + "\n\n" + metadata["rubric"]),
                ChatMessageUser(content=json.dumps(payload, ensure_ascii=False)),
            ],
            config=GenerateConfig(
                max_tokens=8192,
                response_schema=ResponseSchema(name="feedback_assessment", json_schema=json_schema(response_model), strict=True),
            ),
            cache=False,
        )
        judge_response = response_model.model_validate_json(require_text(output)).model_dump()
        # Convert message fields to a chronological list for scoring.
        normalized = dict(judge_response)
        normalized["messages"] = [
            judge_response["messages"][message_id] for message_id in payload["expected_tutor_message_ids"]
        ]
        assessment = Assessment.model_validate(normalized)
        raw_assessment = assessment.model_dump()
        # Preserve the raw judgment before applying the initial-adaptation rule.
        set_initial_adaptation(assessment, metadata["conversation"])
        validate_assessment(assessment, metadata["conversation"], case["answer_annotations"])
        values, counts = summarize_assessment(assessment)
        # Inspect uses NaN for a missing numeric result. It must not become zero.
        for name, value in values.items():
            if value is None:
                values[name] = float("nan")
        return Score(
            value=values,
            explanation="Separate teaching means and cumulative boundary score. Inspect evidence before interpretation.",
            metadata={
                "assessment": assessment.model_dump(),
                "raw_assessment": raw_assessment,
                "raw_response": judge_response,
                "scoring_adjustments": ["Initial adaptation is always null by protocol."],
                "assessable_counts": counts,
                "disclosure_timing": disclosure_timing(assessment),
                "judge_protocol_version": PROTOCOL_VERSION,
            },
        )

    return score


@solver
def require_target_limit():
    async def solve(state, generate):
        model = get_model(role="target", required=True)
        if model.config.max_tokens != 4096:
            raise ValueError("Set max_tokens=4096 in the target model role before running this task.")
        state.metadata["target_max_tokens"] = model.config.max_tokens
        return state

    return solve


def make_task(split, max_replies):
    """Connect the dataset, Petri conversation, and judge."""
    return Task(
        dataset=load_samples(max_replies, split=split),
        solver=[require_target_limit(), audit_solver(auditor=student_driver(), target=target_agent())],
        scorer=feedback_judge(),
        config=GenerateConfig(max_tokens=4096, max_retries=0, timeout=180, fail_on_refusal=True),
    )


@task
def development(max_replies: int = 8):
    return make_task("development", max_replies)


@task
def evaluation(max_replies: int = 8):
    return make_task("evaluation", max_replies)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check experiment inputs without model calls.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--split", choices=("development", "evaluation"), default="development")
    args = parser.parse_args()
    samples = load_samples(8, split=args.split)
    for sample in samples:
        print(sample.id)
    json_schema(StudentStep)
    json_schema(StopDecision)
    json_schema(assessment_response_model(["M2", "M4", "M6"]))
    print(f"{len(samples)} scenarios per target. No model calls were made.")
