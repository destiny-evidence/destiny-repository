"""Tests for the candidate-retrieval policy registry."""

import pytest
from pydantic import ValidationError

from app.domain.references.models.models import (
    CandidateCanonicalSearchFields,
    RetrievalPolicyName,
)
from app.domain.references.models.retrieval_policy import (
    RETRIEVAL_POLICIES,
    YearStrategy,
    resolve_retrieval_policy,
)


def test_resolve_returns_current_fuzzy_v1_regime():
    policy = resolve_retrieval_policy(RetrievalPolicyName.CURRENT_FUZZY_V1)
    assert policy.name is RetrievalPolicyName.CURRENT_FUZZY_V1
    assert policy.union_identifiers is True
    assert policy.year_strategy is YearStrategy.HARD_WINDOW


def test_no_year_filter_v1_regime():
    policy = resolve_retrieval_policy(RetrievalPolicyName.NO_YEAR_FILTER_V1)
    assert policy.name is RetrievalPolicyName.NO_YEAR_FILTER_V1
    assert policy.union_identifiers is True
    assert policy.year_strategy is YearStrategy.NO_FILTER


def test_year_optional_policy_regime():
    policy = resolve_retrieval_policy(
        RetrievalPolicyName.NO_YEAR_FILTER_YEAR_OPTIONAL_V1
    )
    assert policy.year_strategy is YearStrategy.NO_FILTER
    assert policy.requires_publication_year is False


def test_year_required_policies_default_true():
    for name in (
        RetrievalPolicyName.CURRENT_FUZZY_V1,
        RetrievalPolicyName.NO_YEAR_FILTER_V1,
    ):
        assert resolve_retrieval_policy(name).requires_publication_year is True


def test_is_input_searchable_year_optional_admits_missing_year():
    fields = CandidateCanonicalSearchFields(
        title="t", authors=["a"], publication_year=None
    )
    year_optional = resolve_retrieval_policy(
        RetrievalPolicyName.NO_YEAR_FILTER_YEAR_OPTIONAL_V1
    )
    year_required = resolve_retrieval_policy(RetrievalPolicyName.NO_YEAR_FILTER_V1)
    assert year_optional.is_input_searchable(fields) is True
    assert year_required.is_input_searchable(fields) is False


def test_is_input_searchable_requires_title_and_authors():
    fields = CandidateCanonicalSearchFields(
        title="t", authors=[], publication_year=2020
    )
    policy = resolve_retrieval_policy(
        RetrievalPolicyName.NO_YEAR_FILTER_YEAR_OPTIONAL_V1
    )
    assert policy.is_input_searchable(fields) is False


def test_control_year_required_rejects_zero_year_matching_baseline():
    """A zero publication_year is 'no year': the control stays baseline-equivalent."""
    fields = CandidateCanonicalSearchFields(
        title="t", authors=["a"], publication_year=0
    )
    control = resolve_retrieval_policy(RetrievalPolicyName.CURRENT_FUZZY_V1)
    assert control.is_input_searchable(fields) is False
    assert control.is_input_searchable(fields) == fields.is_searchable


def test_policy_name_enum_membership():
    """The value strings are pinned; unknown names are rejected at the boundary."""
    assert (
        RetrievalPolicyName("current_fuzzy_v1") is RetrievalPolicyName.CURRENT_FUZZY_V1
    )
    with pytest.raises(ValueError, match="does_not_exist"):
        RetrievalPolicyName("does_not_exist")


def test_every_policy_name_is_registered():
    """Registry completeness: resolve never misses a member, so the lookup is total."""
    for name in RetrievalPolicyName:
        assert resolve_retrieval_policy(name).name is name


def test_policy_is_immutable():
    policy = resolve_retrieval_policy(RetrievalPolicyName.CURRENT_FUZZY_V1)
    with pytest.raises(ValidationError):
        policy.union_identifiers = False


def test_registry_is_read_only():
    with pytest.raises(TypeError):
        RETRIEVAL_POLICIES["injected"] = resolve_retrieval_policy(
            RetrievalPolicyName.CURRENT_FUZZY_V1
        )


def test_soft_year_decay_v1_regime():
    from app.domain.references.models.models import YearDecayConfig

    assert RetrievalPolicyName.SOFT_YEAR_DECAY_V1.value == "soft_year_decay_v1"
    policy = resolve_retrieval_policy(RetrievalPolicyName.SOFT_YEAR_DECAY_V1)
    assert policy.year_strategy is YearStrategy.SOFT_DECAY
    assert policy.union_identifiers is True
    assert policy.requires_publication_year is True
    assert policy.year_decay == YearDecayConfig()


def test_soft_decay_requires_a_decay_config():
    from app.domain.references.models.retrieval_policy import RetrievalPolicy

    with pytest.raises(ValidationError):
        RetrievalPolicy(
            name=RetrievalPolicyName.SOFT_YEAR_DECAY_V1,
            union_identifiers=True,
            year_strategy=YearStrategy.SOFT_DECAY,
            year_decay=None,
        )


def test_non_soft_decay_rejects_a_decay_config():
    from app.domain.references.models.models import YearDecayConfig
    from app.domain.references.models.retrieval_policy import RetrievalPolicy

    with pytest.raises(ValidationError):
        RetrievalPolicy(
            name=RetrievalPolicyName.CURRENT_FUZZY_V1,
            union_identifiers=True,
            year_strategy=YearStrategy.HARD_WINDOW,
            year_decay=YearDecayConfig(),
        )


def test_soft_decay_policies_unsearchable_without_year():
    """SOFT_DECAY needs a year origin, so a yearless input is not searchable."""
    fields = CandidateCanonicalSearchFields(
        title="t", authors=["a"], publication_year=None
    )
    for name in (
        RetrievalPolicyName.SOFT_YEAR_DECAY_V1,
        RetrievalPolicyName.SOFT_YEAR_DECAY_NONFUZZY_PROBE_V1,
    ):
        assert resolve_retrieval_policy(name).is_input_searchable(fields) is False


def test_soft_year_decay_nonfuzzy_probe_v1_regime():
    policy = resolve_retrieval_policy(
        RetrievalPolicyName.SOFT_YEAR_DECAY_NONFUZZY_PROBE_V1
    )
    assert policy.year_strategy is YearStrategy.SOFT_DECAY
    assert policy.requires_publication_year is True
    assert policy.title_fuzziness == "0"


def test_fuzzy_policies_default_to_auto_fuzziness():
    for name in (
        RetrievalPolicyName.CURRENT_FUZZY_V1,
        RetrievalPolicyName.SOFT_YEAR_DECAY_V1,
    ):
        assert resolve_retrieval_policy(name).title_fuzziness == "AUTO"
