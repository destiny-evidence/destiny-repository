"""
Refresh the ISO -> World Bank region table from the live WB API.

Rewrites the ``ISO_TO_WB_REGION`` block in
``app/domain/references/services/world_bank_regions.py`` in place. Use
``git diff`` to inspect changes; ``git checkout`` to discard.

    uv run python -m app.utils.refresh_world_bank_regions
"""

# ruff: noqa: T201
import json
import re
import sys
import urllib.request
from pathlib import Path

from app.domain.references.services import world_bank_regions

WB_API_URL = "https://api.worldbank.org/v2/country?format=json&per_page=400"
ISO_ALPHA_2_LEN = 2
# WB returns ``JG`` for the Channel Islands aggregate (not a real ISO code).
NON_ISO_CODES_TO_SKIP: frozenset[str] = frozenset({"JG"})

TARGET = Path(world_bank_regions.__file__)
DICT_PATTERN = re.compile(
    r"ISO_TO_WB_REGION: dict\[str, str\] = \{.*?\n\}\n",
    re.DOTALL,
)


def fetch_live_mapping() -> dict[str, str]:
    """Fetch ISO -> WB region ID from the World Bank country API."""
    with urllib.request.urlopen(WB_API_URL) as resp:  # noqa: S310
        payload = json.loads(resp.read())
    mapping: dict[str, str] = {}
    for country in payload[1]:
        iso = country.get("iso2Code", "")
        region_id = country.get("region", {}).get("id", "")
        if (
            len(iso) != ISO_ALPHA_2_LEN
            or iso in NON_ISO_CODES_TO_SKIP
            or region_id in ("", "NA")
        ):
            continue
        mapping[iso] = region_id
    return mapping


def code_to_const_name() -> dict[str, str]:
    """Map each known region code to the module-level constant that holds it."""
    return {
        value: name
        for name, value in vars(world_bank_regions).items()
        if name.isupper()
        and isinstance(value, str)
        and value in world_bank_regions.WORLD_BANK_REGIONS
    }


def render_block(mapping: dict[str, str], const_names: dict[str, str]) -> str:
    """Render the ISO_TO_WB_REGION dict body in the style of the source file."""
    lines = ["ISO_TO_WB_REGION: dict[str, str] = {"]
    for iso in sorted(mapping):
        code = mapping[iso]
        ref = const_names.get(code)
        if ref is None:
            lines.append(f'    "{iso}": {code!r},  # NEW REGION: add a constant')
        else:
            lines.append(f'    "{iso}": {ref},')
    lines.append("}\n")
    return "\n".join(lines)


def main() -> int:
    """Rewrite the static table from the live WB API."""
    mapping = fetch_live_mapping()
    new_block = render_block(mapping, code_to_const_name())

    src = TARGET.read_text()
    new_src, count = DICT_PATTERN.subn(new_block, src, count=1)
    if count != 1:
        print(f"Could not locate ISO_TO_WB_REGION block in {TARGET}", file=sys.stderr)
        return 1
    TARGET.write_text(new_src)
    print(f"Rewrote {TARGET} ({len(mapping)} countries). Inspect with `git diff`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
