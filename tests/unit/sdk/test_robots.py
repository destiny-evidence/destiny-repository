import uuid

import destiny_sdk


def test_enhancement_request_valid():
    enhancement_request = destiny_sdk.robots.EnhancementRequestRead(
        id=uuid.uuid4(),
        reference_id=uuid.uuid4(),
        reference=destiny_sdk.references.Reference(
            id=uuid.uuid4(), visibility=destiny_sdk.visibility.Visibility.RESTRICTED
        ),
        robot_id=uuid.uuid4(),
        request_status=destiny_sdk.robots.EnhancementRequestStatus.RECEIVED,
    )

    assert (
        enhancement_request.request_status
        == destiny_sdk.robots.EnhancementRequestStatus.RECEIVED
    )
    assert enhancement_request.enhancement_parameters is None
    assert enhancement_request.error is None
