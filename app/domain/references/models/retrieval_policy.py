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
from app.domain.references.models.models import (
    CURRENT_FUZZY_RETRIEVAL_POLICY,
    CandidateCanonicalSearchFields,
)


class YearStrategy(Enum):
    """
    How a policy treats the publication-year signal.

    Extension seam: HARD_WINDOW keeps the hard ±1 filter, NO_FILTER drops the
    year clause. A soft year-distance decay strategy (SOFT_DECAY) is added here
    once we have grounding on its weights/policy.
    """

    HARD_WINDOW = "hard_window"
    NO_FILTER = "no_filter"


class RetrievalPolicy(BaseModel):
    """An immutable candidate-retrieval policy bundle."""

    model_config = ConfigDict(frozen=True)

    name: str
    union_identifiers: bool
    year_strategy: YearStrategy
    requires_publication_year: bool = True

    def is_input_searchable(
        self, search_fields: CandidateCanonicalSearchFields
    ) -> bool:
        """Whether the input has the fields this policy needs for ES retrieval."""
        has_core = bool(search_fields.title and search_fields.authors)
        has_year = search_fields.publication_year is not None
        return has_core and (has_year or not self.requires_publication_year)


NO_YEAR_FILTER_POLICY = "no_year_filter_v1"
YEAR_OPTIONAL_POLICY = "no_year_filter_year_optional_v1"


_RETRIEVAL_POLICIES: dict[str, RetrievalPolicy] = {
    policy.name: policy
    for policy in (
        RetrievalPolicy(
            name=CURRENT_FUZZY_RETRIEVAL_POLICY,
            union_identifiers=True,
            year_strategy=YearStrategy.HARD_WINDOW,
        ),
        RetrievalPolicy(
            name=NO_YEAR_FILTER_POLICY,
            union_identifiers=True,
            year_strategy=YearStrategy.NO_FILTER,
        ),
        RetrievalPolicy(
            name=YEAR_OPTIONAL_POLICY,
            union_identifiers=True,
            year_strategy=YearStrategy.NO_FILTER,
            requires_publication_year=False,
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
