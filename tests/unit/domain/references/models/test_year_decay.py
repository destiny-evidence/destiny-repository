"""Tests for publication-year decay models."""

import pytest
from pydantic import ValidationError

from app.domain.references.models.models import (
    YearDecay,
    YearDecayConfig,
)


def test_config_defaults_match_v1_constants():
    config = YearDecayConfig()
    assert (config.offset, config.scale, config.decay, config.weight) == (
        1,
        9,
        0.5,
        0.10,
    )


def test_max_boost_is_derived_from_weight():
    assert YearDecay(origin=2000).max_boost == pytest.approx(1.10)
    assert YearDecay(origin=2000, weight=0.2).max_boost == pytest.approx(1.20)


def test_year_decay_requires_origin():
    with pytest.raises(ValidationError):
        YearDecay()  # origin is required


def test_decay_must_be_below_one():
    with pytest.raises(ValidationError):
        YearDecayConfig(decay=1.0)


def test_config_is_frozen():
    with pytest.raises(ValidationError):
        YearDecayConfig().offset = 5
