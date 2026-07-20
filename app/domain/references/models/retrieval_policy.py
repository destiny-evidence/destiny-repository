"""
Named, immutable candidate-retrieval policies for the Candidate Selection API.

A policy fixes the full retrieval regime under one stable name so recall@K
numbers stay comparable across runs. New policies are added only through a
focused experiment cycle; a policy name's semantics never change.
"""

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict

from app.core.exceptions import DeduplicationValueError
from app.domain.references.models.models import CURRENT_FUZZY_RETRIEVAL_POLICY


class YearStrategy(Enum):
    """
    How a policy treats the publication-year signal.

    Extension seam: HARD_WINDOW is the only strategy today. A soft
    year-distance decay strategy is added here with its policy, not before.
    """

    HARD_WINDOW = "hard_window"


class RetrievalPolicy(BaseModel):
    """An immutable candidate-retrieval policy bundle."""

    model_config = ConfigDict(frozen=True)

    name: str
    union_identifiers: bool
    year_strategy: YearStrategy


_RETRIEVAL_POLICIES: dict[str, RetrievalPolicy] = {
    policy.name: policy
    for policy in (
        RetrievalPolicy(
            name=CURRENT_FUZZY_RETRIEVAL_POLICY,
            union_identifiers=True,
            year_strategy=YearStrategy.HARD_WINDOW,
        ),
    )
}

# Exposed read-only so a policy name's semantics cannot be mutated at runtime.
RETRIEVAL_POLICIES: Mapping[str, RetrievalPolicy] = MappingProxyType(
    _RETRIEVAL_POLICIES
)


def resolve_retrieval_policy(name: str) -> RetrievalPolicy:
    """Return the named policy, or raise DeduplicationValueError if unknown."""
    try:
        return RETRIEVAL_POLICIES[name]
    except KeyError as exc:
        valid = ", ".join(sorted(RETRIEVAL_POLICIES))
        msg = f"Unknown retrieval_policy '{name}'. Valid policies: {valid}."
        raise DeduplicationValueError(msg) from exc
