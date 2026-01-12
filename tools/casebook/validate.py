#!/usr/bin/env python3
"""
Validate deduplication casebook JSON files against schema.

Usage:
    python tools/casebook/validate.py tests/fixtures/dedup_casebook/cases/my_case.json
    python tools/casebook/validate.py tests/fixtures/dedup_casebook/cases/*.json
"""

import json
import sys
from pathlib import Path
from typing import List, Tuple

try:
    import jsonschema
    from jsonschema import Draft7Validator
except ImportError:
    print("Error: jsonschema package not installed")
    print("Install with: pip install jsonschema")
    sys.exit(1)


def load_schema() -> dict:
    """Load the casebook JSON schema."""
    schema_path = Path(__file__).parent.parent.parent / "tests/fixtures/dedup_casebook/schema.json"
    with open(schema_path) as f:
        return json.load(f)


def validate_case_file(case_file: Path, schema: dict) -> Tuple[bool, List[str]]:
    """
    Validate a single case file against the schema.

    Returns:
        (is_valid, errors)
    """
    errors = []

    # Check file exists
    if not case_file.exists():
        return False, [f"File not found: {case_file}"]

    # Check JSON syntax
    try:
        with open(case_file) as f:
            case_data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]

    # Validate against schema
    validator = Draft7Validator(schema)
    schema_errors = list(validator.iter_errors(case_data))

    if schema_errors:
        for error in schema_errors:
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            errors.append(f"{path}: {error.message}")
        return False, errors

    # Additional validations

    # Check case_id matches filename
    expected_case_id = case_file.stem
    if case_data.get("case_id") != expected_case_id:
        errors.append(
            f"case_id '{case_data.get('case_id')}' doesn't match filename '{expected_case_id}'"
        )

    # Check that record references in pairs exist
    if "pairs" in case_data:
        record_keys = set(case_data.get("records", {}).keys())
        for pair in case_data["pairs"]:
            left = pair.get("left_ref")
            right = pair.get("right_ref")
            if left not in record_keys:
                errors.append(f"pairs: left_ref '{left}' not found in records")
            if right not in record_keys:
                errors.append(f"pairs: right_ref '{right}' not found in records")

    # Warn if signals or decision_trace are missing (not errors, just warnings)
    # We don't fail on these, just note them

    return len(errors) == 0, errors


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Load schema once
    try:
        schema = load_schema()
    except Exception as e:
        print(f"Error loading schema: {e}")
        sys.exit(1)

    # Validate all provided files
    case_files = [Path(arg) for arg in sys.argv[1:]]

    all_valid = True
    for case_file in case_files:
        is_valid, errors = validate_case_file(case_file, schema)

        if is_valid:
            print(f"✓ {case_file.name}")
        else:
            print(f"✗ {case_file.name}")
            for error in errors:
                print(f"  - {error}")
            all_valid = False

    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()