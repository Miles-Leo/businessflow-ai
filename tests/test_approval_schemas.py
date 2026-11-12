import pytest
from pydantic import ValidationError

from app.schemas.approval import ApprovalDecisionRequest, ApprovalDecisionResponse


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_valid_decision(decision):
    assert ApprovalDecisionRequest(decision=decision).decision == decision


@pytest.mark.parametrize("payload", [
    {}, {"decision": "pending"}, {"decision": "approve"},
    {"decision": True}, {"decision": None},
    {"decision": "approved", "reviewer_id": "spoofed"},
    {"decision": "approved", "reviewed_at": "2026-11-07T08:00:00Z"},
    {"decision": "approved", "proposal": {}},
    {"decision": "approved", "role": "manager"},
])
def test_invalid_or_extra_fields_are_rejected(payload):
    with pytest.raises(ValidationError):
        ApprovalDecisionRequest.model_validate(payload)


def test_response_serializes_server_review_time():
    response = ApprovalDecisionResponse(
        approval_id="demo-001", approval_status="approved",
        reviewer_id="reviewer-demo-001", reviewed_at="2026-11-07T08:00:00Z",
    )
    assert response.model_dump(mode="json")["reviewed_at"] == "2026-11-07T16:00:00+08:00"


def test_response_requires_timezone():
    with pytest.raises(ValidationError):
        ApprovalDecisionResponse(
            approval_id="demo-001", approval_status="rejected",
            reviewer_id="reviewer-demo-001", reviewed_at="2026-11-07T08:00:00",
        )
