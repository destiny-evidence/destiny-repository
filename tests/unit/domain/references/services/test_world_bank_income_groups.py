"""Unit tests for the ISO -> World Bank income group lookup."""

from typing import get_args

from app.domain.references.services.world_bank_income_groups import (
    HIGH_INCOME,
    ISO_TO_WB_INCOME_GROUP,
    LOWER_MIDDLE_INCOME,
    WORLD_BANK_INCOME_GROUPS,
    WBIncomeGroupID,
    income_groups_for,
)


def test_income_groups_for_maps_known_codes_and_omits_unknown():
    assert income_groups_for({"KE", "US", "ZZ"}) == {LOWER_MIDDLE_INCOME, HIGH_INCOME}


def test_income_groups_for_empty_input():
    assert income_groups_for(set()) == set()


def test_world_bank_income_groups_matches_literal():
    assert set(get_args(WBIncomeGroupID)) == WORLD_BANK_INCOME_GROUPS


def test_lookup_values_are_known_income_groups():
    assert set(ISO_TO_WB_INCOME_GROUP.values()) <= WORLD_BANK_INCOME_GROUPS
