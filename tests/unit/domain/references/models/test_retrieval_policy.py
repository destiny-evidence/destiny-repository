"""Tests for the candidate-retrieval policy registry."""

import pytest
from pydantic import ValidationError

from app.core.exceptions import DeduplicationValueError
from app.domain.references.models.models import CURRENT_FUZZY_RETRIEVAL_POLICY
from app.domain.references.models.retrieval_policy import (
    RETRIEVAL_POLICIES,
    YearStrategy,
    resolve_retrieval_policy,
)


def test_resolve_returns_current_fuzzy_v1_regime():
    policy = resolve_retrieval_policy(CURRENT_FUZZY_RETRIEVAL_POLICY)
    assert policy.name == CURRENT_FUZZY_RETRIEVAL_POLICY
    assert policy.union_identifiers is True
    assert policy.year_strategy is YearStrategy.HARD_WINDOW


def test_resolve_unknown_policy_raises():
    with pytest.raises(DeduplicationValueError) as exc:
        resolve_retrieval_policy("does_not_exist")
    assert "does_not_exist" in str(exc.value)
    assert CURRENT_FUZZY_RETRIEVAL_POLICY in str(exc.value)


def test_current_fuzzy_v1_is_registered():
    assert CURRENT_FUZZY_RETRIEVAL_POLICY in RETRIEVAL_POLICIES


def test_policy_is_immutable():
    policy = resolve_retrieval_policy(CURRENT_FUZZY_RETRIEVAL_POLICY)
    with pytest.raises(ValidationError):
        policy.union_identifiers = False


def test_registry_is_read_only():
    with pytest.raises(TypeError):
        RETRIEVAL_POLICIES["injected"] = resolve_retrieval_policy(
            CURRENT_FUZZY_RETRIEVAL_POLICY
        )
