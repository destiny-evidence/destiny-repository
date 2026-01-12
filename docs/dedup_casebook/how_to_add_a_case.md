# How to Add a Case to the Deduplication Casebook

**Goal**: ≤2 minutes from discovery to committed case

---

## When to Capture a Case

Capture a case **only** when:
- ✅ False positive merge (wrong papers marked as duplicates)
- ✅ False negative (obvious duplicates not found)
- ✅ Dangerous near-miss (would fail if thresholds slightly different)
- ✅ Known pathology you don't want to forget
- ✅ Rule/threshold change that fixes a known issue

**Don't** log every anomaly - only ones that changed your thinking or code.

---

## The 2-Minute Workflow

### Step 1: Create a file (30 seconds)

Location:
```
tests/fixtures/dedup_casebook/cases/
```

Filename pattern:
```
<category>__<short_slug>.json
```

Examples:
```
author_inflation__atlas_false_positive.json
doi_suffix__peer_review_response.json
paper_series__part_1_vs_part_2.json
generic_title__book_reviews.json
```

### Step 2: Copy this minimal template (copy-paste)

```json
{
  "case_id": "category__slug",
  "case_type": "CASE_TYPE_FROM_TAXONOMY",
  "severity": 5,
  "status": "open",
  "summary": "One sentence describing what went wrong",

  "records": {
    "incoming": {
      "source": "crossref",
      "source_key": "10.xxxx/yyyy",
      "title": "Full title here",
      "year": 2024,
      "doi_raw": "10.xxxx/yyyy",
      "authors": ["Author A", "Author B"]
    },
    "candidate": {
      "source": "openalex",
      "source_key": "W1234567890",
      "title": "Different title here",
      "year": 2023,
      "doi_raw": null,
      "authors": ["Author X", "Author Y"]
    }
  },

  "expected_relation": "NOT_DUPLICATE",
  "observed_relation": "DUPLICATE",

  "signals": {
    "es_score": 150.5,
    "title_jaccard": 0.12,
    "author_count_incoming": 2900
  },

  "decision_trace": {
    "candidate_query": "title_authors_v3",
    "short_circuit": "high_es_score"
  },

  "mitigations": [
    "bounded_author_scoring",
    "require_min_jaccard_even_when_es_high"
  ],

  "notes": "Optional context for future reference"
}
```

### Step 3: Fill in the blanks (60 seconds)

**Required fields:**
- `case_id` - same as filename without `.json`
- `case_type` - pick from [taxonomy.md](taxonomy.md)
- `severity` - 1 (info) to 5 (false positive merge)
- `summary` - 1 sentence
- `records` - at least 2 (incoming + candidate)
- `expected_relation` - what SHOULD it be?

**Add if you know them (skip if you don't):**
- `observed_relation` - what DID the system decide?
- `signals` - only the ones that mattered
- `decision_trace` - only if you need to reproduce
- `mitigations` - reference IDs from [mitigations.md](mitigations.md)
- `notes` - only if future-you will forget context

**Unknown ≠ zero. Leave fields out if you don't know them.**

### Step 4: Validate and commit (30 seconds)

```bash
# Validate JSON syntax
python tools/casebook/validate.py tests/fixtures/dedup_casebook/cases/your_case.json

# Commit
git add tests/fixtures/dedup_casebook/cases/your_case.json
git commit -m "casebook: add <category> case for <slug>"
```

---

## Severity Guidelines

- **5**: False positive merge (HIGH confidence, wrong decision, live in prod)
- **4**: False negative miss (obvious dup not found)
- **3**: Near-miss (correct decision but barely; fragile)
- **2**: Edge case (correct decision, worth documenting)
- **1**: Informational (expected behavior)

---

## Case Type Quick Reference

See [taxonomy.md](taxonomy.md) for full definitions.

**Identifier issues:**
- `MALFORMED_DOI_RECOVERABLE` - URL encoding, fragments
- `DOI_COLLISION_DANGEROUS` - same DOI, different papers
- `DOI_SUFFIX_SUPPLEMENT` - `.s001`, `.s002`
- `DOI_SUFFIX_PEER_REVIEW` - `/v1/review`, `/response`

**Title variation (true dups):**
- `TITLE_PUNCTUATION_ARTEFACTS` - "COVID-19" vs "COVID 19"
- `TITLE_ENCODING_NOISE` - HTML tags, entities
- `TITLE_TRUNCATION` - one source truncates

**False positives (not dups):**
- `PAPER_SERIES_PART_CONFUSION` - Part I vs Part II
- `COMMENT_RESPONSE_PAIR` - "Re:", "Response:", "Comment on"
- `AUTHOR_SCORE_INFLATION` - ATLAS-style large author lists
- `FRONTMATTER_BACKMATTER` - "Editorial Board", "Preface"

**System issues:**
- `SCORING_HARDCODED_OUTPUT` - returns 0.950 for everything
- `THRESHOLD_CALIBRATION_NEEDED` - thresholds too loose/strict

---

## Expected Relation Values

- `DUPLICATE` - same intellectual work
- `NOT_DUPLICATE` - distinct works
- `NEEDS_HUMAN` - system can't decide reliably
- `UNSEARCHABLE` - insufficient metadata

---

## Mitigation IDs

Reference mitigations by ID (from [mitigations.md](mitigations.md)):

**Good:**
```json
"mitigations": [
  "bounded_author_scoring",
  "min_jaccard_even_when_es_high",
  "generic_title_blocklist"
]
```

**Bad:**
```json
"mitigations": [
  "fix the author problem",
  "better scoring"
]
```

---

## Multi-Record Clusters (Advanced)

If you have >2 records or need to assert multiple pairs:

```json
{
  "records": {
    "incoming": {...},
    "candidate_1": {...},
    "candidate_2": {...}
  },
  "pairs": [
    {
      "left_ref": "incoming",
      "right_ref": "candidate_1",
      "expected_relation": "NOT_DUPLICATE",
      "observed_relation": "DUPLICATE"
    },
    {
      "left_ref": "incoming",
      "right_ref": "candidate_2",
      "expected_relation": "DUPLICATE",
      "observed_relation": "NOT_DUPLICATE"
    }
  ]
}
```

Most cases won't need this - just use `expected_relation` at the top level for simple 2-record cases.

---

## What NOT to Include

- Don't paste full raw JSON responses (use `source_key` instead)
- Don't copy-paste mitigation descriptions (use IDs)
- Don't add every signal you have (only what mattered)
- Don't overthink severity (pick 3-5 for important cases, 1-2 for edge cases)

---

## After Adding Cases

Cases automatically become:
1. **Regression tests** - `tests/regression/test_dedup_casebook.py` loads and asserts them
2. **Documentation** - searchable record of known failures
3. **Specification** - ground truth for what "duplicate" means

Export to TSV for human review:
```bash
python tools/casebook/export.py --format tsv --out exports/casebook.tsv
```

Export to Parquet for analysis:
```bash
python tools/casebook/export.py --format parquet --out exports/casebook.parquet
```

---

## Example: Complete Minimal Case

File: `tests/fixtures/dedup_casebook/cases/author_inflation__atlas_001.json`

```json
{
  "case_id": "author_inflation__atlas_001",
  "case_type": "AUTHOR_SCORE_INFLATION",
  "severity": 5,
  "status": "open",
  "summary": "Large ATLAS collaboration author list inflated ES score, merged unrelated papers",

  "records": {
    "incoming": {
      "source": "crossref",
      "source_key": "10.1007/JHEP11(2020)005",
      "title": "Continuous calibration of ATLAS flavour-tagging classifiers using R=0.4 jets",
      "year": 2020,
      "doi_raw": "10.1007/JHEP11(2020)005",
      "authors": ["ATLAS Collaboration"]
    },
    "candidate": {
      "source": "openalex",
      "source_key": "W2963166742",
      "title": "Modeling growth of natural microbiota in Frankfurt-type sausages",
      "year": 2019,
      "doi_raw": null,
      "authors": ["Smith J", "Müller K"]
    }
  },

  "expected_relation": "NOT_DUPLICATE",
  "observed_relation": "DUPLICATE",

  "signals": {
    "es_score": 2780.1,
    "title_jaccard": 0.12,
    "author_count_incoming": 2900
  },

  "mitigations": [
    "bounded_author_scoring",
    "require_min_jaccard_even_when_es_high"
  ]
}
```

That's it. No more than 2 minutes.
