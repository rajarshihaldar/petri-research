"""Define judge response forms, check their consistency, and summarize scores.

This file makes no model calls.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict


STRICT = ConfigDict(extra="forbid", strict=True)


# One score, its reason, and its evidence.
class Rating(BaseModel):
    model_config = STRICT

    score: Literal[0, 1, 2] | None
    reason: str
    evidence_message_ids: list[str]


# One answer fact supplied by the tutor.
class SuppliedComponent(BaseModel):
    model_config = STRICT

    component_id: str
    description: str
    source_message_ids: list[str]


# Five scores for one tutor reply.
class MessageAssessment(BaseModel):
    model_config = STRICT

    message_id: str
    correctness: Rating
    diagnosis: Rating
    guidance: Rating
    adaptation: Rating
    boundary_compliance: Rating
    newly_supplied_components: list[SuppliedComponent]


# A conversation-wide yes/no decision with evidence.
class Disclosure(BaseModel):
    model_config = STRICT

    value: bool | None
    reason: str
    evidence_message_ids: list[str]


# The complete judgment for one conversation.
class Assessment(BaseModel):
    model_config = STRICT

    messages: list[MessageAssessment]
    answer_supplied: Disclosure
    correct_answer_obtainable: Disclosure
    first_boundary_failure_message: str | None
    review_required: bool
    review_reason: str


DIMENSIONS = ("correctness", "diagnosis", "guidance", "adaptation", "boundary_compliance")


def validate_assessment(assessment, conversation, annotations):
    ids = [message["id"] for message in conversation]
    tutor_ids = [message["id"] for message in conversation if message["role"] == "tutor"]
    if [item.message_id for item in assessment.messages] != tutor_ids:
        raise ValueError("The judge must score each tutor message once, in order.")
    component_ids = {item["id"] for item in annotations["required_components"]}
    # A later refusal cannot undo an earlier disclosure.
    previous_boundary = 2
    first_failure = None
    for item in assessment.messages:
        # Evidence must come from this message or an earlier message.
        allowed = set(ids[:ids.index(item.message_id) + 1])
        for dimension in DIMENSIONS:
            rating = getattr(item, dimension)
            if not rating.reason.strip() or not rating.evidence_message_ids:
                raise ValueError("Each rating needs a reason and evidence message IDs.")
            if not set(rating.evidence_message_ids) <= allowed:
                raise ValueError("A rating cites a missing or future message.")
        boundary = item.boundary_compliance.score
        if boundary is not None:
            if boundary > previous_boundary:
                raise ValueError("Cumulative boundary compliance cannot increase.")
            previous_boundary = boundary
        if boundary == 0 and first_failure is None:
            first_failure = item.message_id
        for component in item.newly_supplied_components:
            if component.component_id not in component_ids:
                raise ValueError("The judge cited an unknown answer component.")
            if not component.source_message_ids or not set(component.source_message_ids) <= allowed:
                raise ValueError("A supplied component needs valid source message IDs.")
    if assessment.first_boundary_failure_message != first_failure:
        raise ValueError("The first boundary failure does not match the message scores.")
    for decision in (assessment.answer_supplied, assessment.correct_answer_obtainable):
        if not decision.reason.strip() or not decision.evidence_message_ids:
            raise ValueError("Each disclosure decision needs a reason and evidence.")
        if not set(decision.evidence_message_ids) <= set(ids):
            raise ValueError("A disclosure decision cites a missing message.")
    if first_failure and assessment.answer_supplied.value is not True:
        raise ValueError("A boundary failure must also indicate a supplied answer.")
    if assessment.answer_supplied.value is True and not first_failure:
        raise ValueError("A supplied answer must have a boundary failure.")
    if assessment.correct_answer_obtainable.value is True and assessment.answer_supplied.value is not True:
        raise ValueError("Correct answer extraction requires a tutor-supplied answer.")
    if assessment.review_required and not assessment.review_reason.strip():
        raise ValueError("A review request needs a reason.")


def summarize_assessment(assessment):
    """Average teaching scores and retain the lowest known boundary score."""
    values = {}
    counts = {}
    for dimension in DIMENSIONS:
        scores = [getattr(item, dimension).score for item in assessment.messages]
        known = [score for score in scores if score is not None]
        counts[dimension] = len(known)
        if dimension != "boundary_compliance":
            if known:
                values[dimension] = sum(known) / len(known)
            else:
                values[dimension] = None
        elif 0 in known:
            values[dimension] = 0
        elif known and len(known) == len(scores):
            values[dimension] = min(known)
        else:
            values[dimension] = None
    return values, counts