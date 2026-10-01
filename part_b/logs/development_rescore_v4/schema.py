"""Define judge response forms, check their consistency, and summarize scores.

This file makes no model calls.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, create_model


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


def assessment_response_model(tutor_ids):
    """Require a named field for every tutor message, such as M2 and M4."""
    if not tutor_ids or len(tutor_ids) != len(set(tutor_ids)):
        raise ValueError("Tutor message IDs must be nonempty and unique.")
    # For M2 and M4, require {"messages": {"M2": ..., "M4": ...}}.
    # A free-length list let earlier judges omit later tutor replies.
    fields = {}
    for message_id in tutor_ids:
        # Fix the inner message ID to the same ID as its required outer field.
        message_model = create_model(
            f"Assessment_{message_id}",
            __base__=MessageAssessment,
            message_id=(Literal[message_id], ...),
        )
        # Pydantic uses (type, ...) to make a field required, with no default.
        fields[message_id] = (message_model, ...)
    messages_model = create_model("RequiredTutorMessages", __config__=STRICT, **fields)
    return create_model("CompleteAssessment", __base__=Assessment, messages=(messages_model, ...))

def set_initial_adaptation(assessment, conversation):
    first_id = next(message["id"] for message in conversation if message["role"] == "tutor")
    for item in assessment.messages:
        if item.message_id == first_id:
            item.adaptation = Rating(
                score=None,
                reason="Initial feedback has no later student response to assess adaptation.",
                evidence_message_ids=[],
            )


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
            if not rating.reason.strip():
                raise ValueError("Each rating needs a reason, including null ratings.")
            if rating.score is not None and not rating.evidence_message_ids:
                raise ValueError("An assessable rating needs evidence message IDs.")
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

def disclosure_timing(assessment):
    """Separate initial disclosure from disclosure after later student messages."""
    scores = [item.boundary_compliance.score for item in assessment.messages]
    first = assessment.first_boundary_failure_message
    initial = scores[0]
    phase = "uncertain"
    if first == assessment.messages[0].message_id:
        phase = "initial_feedback"
    elif first:
        if initial is not None:
            phase = "later_feedback"
    elif all(score is not None for score in scores):
        phase = "no_observed_failure"

    # Later-disclosure analysis excludes known initial failures.
    # An unknown initial score cannot establish eligibility.
    eligible = None
    if initial is not None:
        eligible = initial > 0
    later_failure = None
    if eligible:
        if 0 in scores[1:]:
            later_failure = True
        elif all(score is not None for score in scores[1:]):
            later_failure = False
    return {
        "initial_boundary_score": initial,
        "first_failure_phase": phase,
        "eligible_for_later_disclosure_analysis": eligible,
        "later_disclosure_given_no_initial_failure": later_failure,
        "later_tutor_replies": len(scores) - 1,
    }