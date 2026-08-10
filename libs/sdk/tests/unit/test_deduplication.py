from uuid import uuid7

import destiny_sdk


def test_make_duplicate_decision_result_parses_response_without_provenance():
    """A newer SDK must still parse a server that predates the provenance fields."""
    obj = destiny_sdk.deduplication.MakeDuplicateDecisionResult.model_validate(
        {
            "id": str(uuid7()),
            "reference_id": str(uuid7()),
            "outcome": "canonical",
            "active_decision": True,
        }
    )

    assert (
        obj.decision_authority
        == destiny_sdk.deduplication.DuplicateDecisionAuthority.UNCLASSIFIED
    )
    assert (
        obj.decision_trigger
        == destiny_sdk.deduplication.DuplicateDecisionTrigger.UNCLASSIFIED
    )


def test_make_duplicate_decision_result_keeps_provenance_when_sent():
    obj = destiny_sdk.deduplication.MakeDuplicateDecisionResult.model_validate(
        {
            "id": str(uuid7()),
            "reference_id": str(uuid7()),
            "outcome": "canonical",
            "active_decision": True,
            "decision_authority": "person",
            "decision_trigger": "manual_api",
        }
    )

    assert (
        obj.decision_authority
        == destiny_sdk.deduplication.DuplicateDecisionAuthority.PERSON
    )
    assert (
        obj.decision_trigger
        == destiny_sdk.deduplication.DuplicateDecisionTrigger.MANUAL_API
    )
