"""Run the conversations and score the tutor feedback.

Call order: tutor, student, then repeat. Judge once at the end.
The student call also decides whether to stop. There is no separate stop call.
The opening is fixed text. Only the judge receives private answer annotations.
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

from schema import Assessment, disclosure_timing, summarize_assessment, validate_assessment


# Response forms for the student and conversation control.
class StudentStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message: str | None
    stop_reason: Literal["continue", "confirmed_answer", "final_refusal"]
    evidence_message_id: str | None


BASE = Path(__file__).parent
CONDITIONS = {
    "ordinary": "Ordinary feedback",
    "direct": "Direct answer pressure",
    "gradual": "Gradual answer requests",
}
PUBLIC_FIELDS = ("assignment", "input_assumptions", "code", "student_response")
PROTOCOL_VERSION = "0.2"


def read_text(relative):
    return (BASE / relative).read_text().strip()


def render_opening(case, template):
    for field in PUBLIC_FIELDS:
        template = template.replace("{{" + field + "}}", case[field])
    if "{{" in template:
        raise ValueError("The opening message has an unresolved placeholder.")
    return template


def auditor_prompt(text, heading):
    shared, *sections = text.split("\n## ")
    for section in sections:
        title, body = section.split("\n", 1)
        if title.strip() == heading:
            return shared + "\n\n## " + title + "\n" + body
    raise ValueError("The requested auditor condition is missing.")


def load_samples(max_replies):
    if not 2 <= max_replies <= 8:
        raise ValueError("Development requires between 2 and 8 tutor replies.")
    cases = json.loads(read_text("data/selected/development.json"))
    if len(cases) != 2 or len({case["case_id"] for case in cases}) != 2:
        raise ValueError("The development dataset must contain two distinct cases.")
    texts = {name: read_text(f"prompts/{name}.md") for name in ("tutor", "auditor", "opening", "judge")}
    texts["rubric"] = read_text("rubric.md")
    hashes = {name: hashlib.sha256(text.encode()).hexdigest() for name, text in texts.items()}
    samples = []
    for case in cases:
        annotations = case.get("answer_annotations", {})
        if case["split"] != "development" or not annotations.get("required_components"):
            raise ValueError("Each development case needs answer annotations.")
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


async def generate_student_step(state, model, config, prompt, request):
    """Call the auditor to produce one student step and record its output."""
    output = await model.generate(
        input=[ChatMessageSystem(content=prompt), request], config=config, cache=False,
    )
    state.messages.extend([request, output.message])
    state.output = output
    return StudentStep.model_validate_json(require_text(output))


@agent
def student_driver() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        ctrl = controller()
        metadata = ctrl.state.metadata
        conversation = []
        metadata["conversation"] = conversation
        metadata["conversation_complete"] = False
        metadata["stop_reason"] = "incomplete"
        # Both student generation and stopping use the auditor role.
        student_model = get_model(role="auditor", required=True)
        student_config = GenerateConfig(
            max_tokens=2048,
            response_schema=ResponseSchema(name="student_step", json_schema=json_schema(StudentStep), strict=True),
        )
        await ctrl.stage_system(metadata["tutor_prompt"])
        student_message = metadata["opening"]
        state.messages[:] = []
        # Each iteration sends one student message and receives one tutor reply.
        for reply in range(metadata["max_replies"]):
            await ctrl.stage_user(student_message)
            conversation.append({"id": f"M{len(conversation) + 1}", "role": "student", "text": student_message})
            response = await ctrl.resume(expected=ResponseOutput)
            tutor_text = require_text(response.output)
            conversation.append({"id": f"M{len(conversation) + 1}", "role": "tutor", "text": tutor_text})
            # At the reply limit, stop without another model call.
            if reply + 1 == metadata["max_replies"]:
                metadata["stop_reason"] = "reply_limit"
                break
            request = ChatMessageUser(content=json.dumps({"conversation": conversation}, ensure_ascii=False))
            step = await generate_student_step(
                state, student_model, student_config, metadata["auditor_prompt"], request,
            )
            if step.stop_reason != "continue":
                if step.message is not None or step.evidence_message_id != conversation[-1]["id"]:
                    raise ValueError("A stop decision must cite the latest tutor message and have a null message.")
                metadata["stop_reason"] = step.stop_reason
                metadata["stop_evidence_message_id"] = step.evidence_message_id
                break
            if not step.message or not step.message.strip() or step.evidence_message_id is not None:
                raise ValueError("A continuation needs a student message and a null evidence ID.")
            student_message = step.message
        metadata["conversation_complete"] = True
        return state

    return execute


@scorer(metrics={"boundary_compliance": [mean()]})
def feedback_judge() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        metadata = state.metadata
        if not metadata.get("conversation_complete"):
            raise ValueError("Do not score an incomplete conversation.")
        case = metadata["case"]
        # The judge receives the reference answer and private annotations.
        case_fields = (*PUBLIC_FIELDS, "reference_answer", "misconception", "answer_annotations")
        payload = {
            "case": {field: case[field] for field in case_fields},
            "tutor_instructions": metadata["tutor_prompt"],
            "conversation": metadata["conversation"],
            "expected_tutor_message_ids": [
                message["id"] for message in metadata["conversation"] if message["role"] == "tutor"
            ],
        }
        output = await get_model(role="judge", required=True).generate(
            input=[
                ChatMessageSystem(content=metadata["judge_prompt"] + "\n\n" + metadata["rubric"]),
                ChatMessageUser(content=json.dumps(payload, ensure_ascii=False)),
            ],
            config=GenerateConfig(
                max_tokens=8192,
                response_schema=ResponseSchema(name="feedback_assessment", json_schema=json_schema(Assessment), strict=True),
            ),
            cache=False,
        )
        assessment = Assessment.model_validate_json(require_text(output))
        validate_assessment(assessment, metadata["conversation"], case["answer_annotations"])
        values, counts = summarize_assessment(assessment)
        # Inspect represents missing numeric scores with NaN.
        for name, value in values.items():
            if value is None:
                values[name] = float("nan")
        return Score(
            value=values,
            explanation="Separate teaching means and cumulative boundary score. Inspect evidence before interpretation.",
            metadata={
                "assessment": assessment.model_dump(),
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


@task
def development(max_replies: int = 8):
    return Task(
        dataset=load_samples(max_replies),
        solver=[require_target_limit(), audit_solver(auditor=student_driver(), target=target_agent())],
        scorer=feedback_judge(),
        config=GenerateConfig(max_tokens=4096, max_retries=0, timeout=180, fail_on_refusal=True),
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check development inputs without model calls.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    samples = load_samples(8)
    for sample in samples:
        print(sample.id)
    json_schema(StudentStep)
    json_schema(Assessment)
    print("Six scenarios per target. No model calls were made.")
