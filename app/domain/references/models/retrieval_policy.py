"""
Named, immutable candidate-retrieval policies for the Candidate Selection API.

A policy fixes the full retrieval regime under one stable name so recall@K
numbers stay comparable across runs. New policies are added only through a
focused experiment cycle; a policy name's semantics never change.
"""

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.domain.references.models.models import (
    CandidateCanonicalSearchFields,
    RetrievalPolicyName,
    YearDecayConfig,
)


class YearStrategy(Enum):
    """
    How a policy treats the publication-year signal.

    Extension seam: HARD_WINDOW keeps the hard ±1 filter, NO_FILTER drops the
    year clause, SOFT_DECAY drops the hard filter and instead applies a bounded
    year-proximity bonus.
    """

    HARD_WINDOW = "hard_window"
    NO_FILTER = "no_filter"
    SOFT_DECAY = "soft_decay"


class RetrievalPolicy(BaseModel):
    """An immutable candidate-retrieval policy bundle."""

    model_config = ConfigDict(frozen=True)

    name: RetrievalPolicyName
    union_identifiers: bool
    year_strategy: YearStrategy
    requires_publication_year: bool = True
    year_decay: YearDecayConfig | None = None

    @model_validator(mode="after")
    def _validate_year_decay_matches_strategy(self) -> Self:
        """year_decay is present iff the strategy is SOFT_DECAY."""
        if (self.year_decay is not None) != (
            self.year_strategy is YearStrategy.SOFT_DECAY
        ):
            msg = "year_decay must be set iff year_strategy is SOFT_DECAY."
            raise ValueError(msg)
        return self

    def is_input_searchable(
        self, search_fields: CandidateCanonicalSearchFields
    ) -> bool:
        """Whether the input has the fields this policy needs for ES retrieval."""
        has_core = bool(search_fields.title and search_fields.authors)
        # Falsy year (0/None) counts as absent, matching the baseline all(...) gate.
        has_year = bool(search_fields.publication_year)
        return has_core and (has_year or not self.requires_publication_year)


# Wrapped read-only with no module-level handle to the backing dict, so a policy
# name's semantics cannot be remapped at runtime.
RETRIEVAL_POLICIES: Mapping[RetrievalPolicyName, RetrievalPolicy] = MappingProxyType(
    {
        policy.name: policy
        for policy in (
            RetrievalPolicy(
                name=RetrievalPolicyName.CURRENT_FUZZY_V1,
                union_identifiers=True,
                year_strategy=YearStrategy.HARD_WINDOW,
            ),
            RetrievalPolicy(
                name=RetrievalPolicyName.NO_YEAR_FILTER_V1,
                union_identifiers=True,
                year_strategy=YearStrategy.NO_FILTER,
            ),
            RetrievalPolicy(
                name=RetrievalPolicyName.NO_YEAR_FILTER_YEAR_OPTIONAL_V1,
                union_identifiers=True,
                year_strategy=YearStrategy.NO_FILTER,
                requires_publication_year=False,
            ),
            RetrievalPolicy(
                name=RetrievalPolicyName.SOFT_YEAR_DECAY_V1,
                union_identifiers=True,
                year_strategy=YearStrategy.SOFT_DECAY,
                year_decay=YearDecayConfig(),
            ),
        )
    }
)


def resolve_retrieval_policy(name: RetrievalPolicyName) -> RetrievalPolicy:
    """Return the immutable policy bundle registered under this name."""
    return RETRIEVAL_POLICIES[name]
