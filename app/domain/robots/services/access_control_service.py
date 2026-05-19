"""Access control for robots."""

from fastapi import status

from app.api.auth import Entitlement
from app.core.exceptions import AuthError
from app.domain.service import GenericAccessControlService


class RobotAccessControlService(GenericAccessControlService):
    """Apply the principal's entitlements to robot write operations."""

    def resolve_robot_entitlements(
        self,
        submitted: frozenset[Entitlement],
        existing: frozenset[Entitlement],
    ) -> frozenset[Entitlement]:
        """Return the entitlements to persist, enforcing the writer requirement."""
        # Writers may set entitlements freely, including revoking via an empty set.
        if Entitlement.ROBOT_ENTITLEMENT_WRITER in self._entitlements:
            return submitted
        # Everyone else may only submit no-op inputs: an empty set (treated as
        # "field not specified") or the existing value (round-trip from GET).
        if not submitted or submitted == existing:
            return existing
        raise AuthError(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Changing robot entitlements requires the "
                "robot.entitlement.writer scope or role."
            ),
        )
