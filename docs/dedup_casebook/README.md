# Deduplication Casebook

A structured repository of deduplication edge cases, failures, and system issues discovered during testing and production use.

## Purpose

The casebook serves multiple purposes:

1. **Documentation** - Searchable record of known deduplication challenges
2. **Regression Testing** - Ground truth assertions that prevent backsliding
3. **Team Communication** - Shared understanding of what "duplicate" means
4. **Continuous Evaluation** - Dataset for measuring dedup algorithm improvements

## Quick Start

### Adding a Case (2 minutes)

See [how_to_add_a_case.md](how_to_add_a_case.md) for the complete workflow.

Quick version:

1. Create a file: `tests/fixtures/dedup_casebook/cases/<category>__<slug>.json`
2. Copy the minimal template from the workflow doc
3. Fill in: case_type, severity, records, expected_relation
4. Validate and commit

### Validating Cases

```bash
# Validate a single case
python tools/casebook/validate.py tests/fixtures/dedup_casebook/cases/my_case.json

# Validate all cases
python tools/casebook/validate.py tests/fixtures/dedup_casebook/cases/*.json
```

## Structure

```
docs/dedup_casebook/
├── README.md              # This file
├── taxonomy.md            # Case type definitions
├── mitigations.md         # Mitigation reference
└── how_to_add_a_case.md   # Workflow guide

tests/fixtures/dedup_casebook/
├── schema.json            # JSON schema
└── cases/                 # Case files
    ├── author_inflation__atlas_001.json
    ├── paper_series__quantum_hall_part_1_vs_2.json
    ├── comment_response__cisplatin_therapy.json
    ├── doi_suffix__peer_review_v2.json
    ├── doi_suffix__acs_supplement.json
    ├── generic_title__book_reviews.json
    └── scoring__hardcoded_0950.json

tools/casebook/
└── validate.py            # Validator script
```

## Key Documents

- **[taxonomy.md](taxonomy.md)** - Complete list of case types with definitions and examples
- **[mitigations.md](mitigations.md)** - Reference of all mitigation IDs and their implementations
- **[how_to_add_a_case.md](how_to_add_a_case.md)** - Step-by-step workflow for adding cases

## Case Types Overview

### Identifier Problems (7 types)
- Malformed DOIs
- DOI collisions
- DOI suffixes (supplements, peer review, versions)
- Missing identifiers

### Title Variation (5 types)
- Punctuation/encoding
- Translations
- Truncation
- Preprint drift

### False Positives (7 types)
- Paper series (Part 1 vs Part 2)
- Comment/response pairs
- Author score inflation (ATLAS-style)
- Generic titles (Book Reviews, etc.)
- Supplementary materials
- Peer review artifacts

### System Issues (4 types)
- Hardcoded scores
- Streaming timeouts
- Threshold calibration

See [taxonomy.md](taxonomy.md) for complete definitions.

## Philosophy

### What to Log

✅ **Log these:**
- False positive merges (severity 5)
- False negative misses (severity 4)
- Dangerous near-misses (severity 3)
- System pathologies worth remembering

❌ **Don't log these:**
- Every anomaly (only ones that changed your thinking)
- Expected behavior
- One-off quirks with no pattern

### Speed Matters

If adding a case takes more than 2 minutes, the system is wrong. The workflow is designed for:
- Fast capture during debugging
- No schema thinking required
- Optional detail (unknown ≠ zero)

### Migration Path

**Current**: JSON fixtures (fast, git-native, PR-friendly)

**Future options**:
- SQLite for ad-hoc queries
- Parquet for analytics
- Dashboards for visualization

Don't build these until you have 20-30 cases. Until then, JSON + grep + git diff are superior.

## Example Cases

See `tests/fixtures/dedup_casebook/cases/` for concrete examples:

1. **author_inflation__atlas_001.json** - Large collaboration false positive
2. **paper_series__quantum_hall_part_1_vs_2.json** - Multi-part paper confusion
3. **comment_response__cisplatin_therapy.json** - Comment/response not distinguished
4. **doi_suffix__peer_review_v2.json** - Peer review artifacts
5. **doi_suffix__acs_supplement.json** - Supplementary material suffixes
6. **generic_title__book_reviews.json** - Generic title collision
7. **scoring__hardcoded_0950.json** - System issue with hardcoded scores

## Integration with Testing

Cases automatically feed regression tests via `tests/regression/test_dedup_casebook.py`:

```python
def test_casebook_expected_relations(load_casebook, dedup_engine):
    for case in load_casebook():
        result = dedup_engine.evaluate(case["records"])
        assert result.relation == case["expected_relation"], case["case_id"]
```

This ensures known failures stay fixed.

## Presentation Use

For team presentations, focus on:

1. **Tensions and challenges**, not solutions
2. **Policy questions** - what IS a duplicate?
3. **Unknown unknowns** - issues still emerging
4. **Concrete examples** from the casebook

The casebook is "executable knowledge" - it captures both the problem and what we learned.

## Next Steps

1. Add cases as you discover anomalies
2. Reference cases in PR discussions
3. Link mitigations to cases
4. Use cases to measure algorithm improvements
5. Export to TSV/Parquet when analysis needed

## Questions?

See the workflow guide: [how_to_add_a_case.md](how_to_add_a_case.md)
