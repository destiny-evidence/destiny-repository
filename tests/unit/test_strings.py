"""Tests for string utilities, including the mojibake display remap."""

from typing import Any

import pytest

from app.utils.strings import demojibake, demojibake_walk


def _mojibake(value: str) -> str:
    """Reproduce mojibaked chars: UTF-8 bytes misdecoded as latin-1."""
    return value.encode("utf-8").decode("latin-1")


_CURLY_CLEAN = "Teachers’ training"  # noqa: RUF001
_QUOTED_CLEAN = "literal ’quoted’"  # noqa: RUF001


class TestDemojibake:
    """Tests for the single-string mojibake remap."""

    @pytest.mark.parametrize(
        "clean",
        [
            _CURLY_CLEAN,
            "a café and a naïve résumé",
            "«guillemets» and — em dashes",
            "Über die Grénze",
        ],
    )
    def test_reverses_latin1_misdecode(self, clean: str) -> None:
        assert demojibake(_mojibake(clean)) == clean

    @pytest.mark.parametrize(
        "text",
        [
            "ASCII only",
            "café",  # accented char not followed by a continuation byte
            "naïve",
            "Beyoncé",
            "à la carte",
            "£5 and 50¢",
            "Zürich",
            "こんにちは",  # already-clean multi-byte text
        ],
    )
    def test_leaves_clean_text_untouched(self, text: str) -> None:
        assert demojibake(text) is text

    def test_leaves_non_round_tripping_match_untouched(self) -> None:
        # Matches the signature but is not valid UTF-8 when re-encoded.
        assert demojibake("Aâ\x80Z\x80") == "Aâ\x80Z\x80"

    def test_is_idempotent(self) -> None:
        once = demojibake(_mojibake(_CURLY_CLEAN))
        assert demojibake(once) == once


class TestDemojibakeTextValues:
    """Tests for the in-place, key-scoped structural remap."""

    def test_repairs_only_allowlisted_keys(self) -> None:
        text_keys = frozenset({"title", "display_name"})
        node = {
            "title": _mojibake(_CURLY_CLEAN),
            "publisher": _mojibake("Éditeur"),  # not in the allowlist
        }

        demojibake_walk(node, text_keys)

        assert node["title"] == _CURLY_CLEAN
        assert node["publisher"] == _mojibake("Éditeur")

    def test_recurses_nested_mappings_and_lists(self) -> None:
        text_keys = frozenset({"display_name", "description"})
        node: dict[str, Any] = {
            "authorship": [{"display_name": _mojibake("José"), "orcid": "0000-0002"}],
            "description": [_mojibake("First"), _mojibake("Sécond")],
        }

        demojibake_walk(node, text_keys)

        assert node["authorship"][0]["display_name"] == "José"
        assert node["authorship"][0]["orcid"] == "0000-0002"
        assert node["description"] == ["First", "Sécond"]

    def test_never_touches_identifiers_under_a_text_key(self) -> None:
        # A JSON-LD literal object nested under a text key must still have its
        # own @id/@type left alone; only @value is a text key here.
        text_keys = frozenset({"supportingText", "@value"})
        unsafe_id = "https://id.example.org/" + _mojibake("Ünsafe")
        node = {
            "supportingText": {
                "@value": _mojibake(_QUOTED_CLEAN),
                "@id": unsafe_id,
                "@type": "xsd:string",
            }
        }

        demojibake_walk(node, text_keys)

        assert node["supportingText"]["@value"] == _QUOTED_CLEAN
        assert node["supportingText"]["@id"] == unsafe_id
