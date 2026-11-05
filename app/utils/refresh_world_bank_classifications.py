"""
Refresh the ISO -> World Bank classification tables from the live WB API.

Rewrites the ``ISO_TO_WB_REGION`` block in
``app/domain/references/services/world_bank_regions.py`` and the
``ISO_TO_WB_INCOME_GROUP`` block in
``app/domain/references/services/world_bank_income_groups.py`` in place. Use
``git diff`` to inspect changes; ``git checkout`` to discard.

    uv run python -m app.utils.refresh_world_bank_classifications
"""

# ruff: noqa: T201
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from app.domain.references.services import (
    world_bank_income_groups,
    world_bank_regions,
)

WB_API_URL = "https://api.worldbank.org/v2/country?format=json&per_page=400"
ISO_ALPHA_2_LEN = 2
# WB returns ``JG`` for the Channel Islands aggregate (not a real ISO code).
NON_ISO_CODES_TO_SKIP: frozenset[str] = frozenset({"JG"})


@dataclass(frozen=True)
class ClassificationTable:
    """A static ISO -> WB classification table and where it comes from."""

    module: ModuleType
    dict_name: str
    response_key: str
    known_ids: frozenset[str]
    ids_to_skip: frozenset[str]

    @property
    def target(self) -> Path:
        """Source file holding the table."""
        return Path(str(self.module.__file__))

    @property
    def dict_pattern(self) -> re.Pattern[str]:
        """Pattern matching the table's dict literal in the source file."""
        return re.compile(
            rf"{self.dict_name}: dict\[str, str\] = \{{.*?\n\}}\n",
            re.DOTALL,
        )


TABLES: tuple[ClassificationTable, ...] = (
    ClassificationTable(
        module=world_bank_regions,
        dict_name="ISO_TO_WB_REGION",
        response_key="region",
        known_ids=world_bank_regions.WORLD_BANK_REGIONS,
        ids_to_skip=frozenset({"", "NA"}),
    ),
    ClassificationTable(
        module=world_bank_income_groups,
        dict_name="ISO_TO_WB_INCOME_GROUP",
        response_key="incomeLevel",
        known_ids=world_bank_income_groups.WORLD_BANK_INCOME_GROUPS,
        ids_to_skip=frozenset({"", "NA", "INX"}),
    ),
)


def fetch_countries() -> list[dict[str, Any]]:
    """Fetch every country record from the World Bank country API."""
    with urllib.request.urlopen(WB_API_URL) as resp:  # noqa: S310
        payload = json.loads(resp.read())
    return payload[1]


def build_mapping(
    countries: list[dict[str, Any]], table: ClassificationTable
) -> dict[str, str]:
    """Map ISO -> classification ID for one table."""
    mapping: dict[str, str] = {}
    for country in countries:
        iso = country.get("iso2Code", "")
        classification_id = country.get(table.response_key, {}).get("id", "")
        if (
            len(iso) != ISO_ALPHA_2_LEN
            or iso in NON_ISO_CODES_TO_SKIP
            or classification_id in table.ids_to_skip
        ):
            continue
        mapping[iso] = classification_id
    return mapping


def code_to_const_name(table: ClassificationTable) -> dict[str, str]:
    """Map each known classification ID to the module constant that holds it."""
    return {
        value: name
        for name, value in vars(table.module).items()
        if name.isupper() and isinstance(value, str) and value in table.known_ids
    }


def render_block(
    mapping: dict[str, str], const_names: dict[str, str], dict_name: str
) -> str:
    """Render a classification dict body in the style of the source file."""
    lines = [f"{dict_name}: dict[str, str] = {{"]
    for iso in sorted(mapping):
        code = mapping[iso]
        ref = const_names.get(code)
        if ref is None:
            lines.append(f'    "{iso}": {code!r},  # NEW ID: add a constant')
        else:
            lines.append(f'    "{iso}": {ref},')
    lines.append("}\n")
    return "\n".join(lines)


def rewrite_table(countries: list[dict[str, Any]], table: ClassificationTable) -> bool:
    """Rewrite one table in place from the fetched countries."""
    mapping = build_mapping(countries, table)
    new_block = render_block(mapping, code_to_const_name(table), table.dict_name)

    src = table.target.read_text()
    new_src, count = table.dict_pattern.subn(new_block, src, count=1)
    if count != 1:
        print(
            f"Could not locate {table.dict_name} block in {table.target}",
            file=sys.stderr,
        )
        return False
    table.target.write_text(new_src)
    print(f"Rewrote {table.target} ({len(mapping)} countries).")
    return True


def main() -> int:
    """Rewrite the static tables from the live WB API."""
    countries = fetch_countries()
    results = [rewrite_table(countries, table) for table in TABLES]
    print("Inspect with `git diff`.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
