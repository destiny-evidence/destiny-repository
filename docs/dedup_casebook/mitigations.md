# Deduplication Mitigations Reference

This document defines all mitigation IDs referenced in casebook cases. Each mitigation answers:
- What it is
- Where it lives (code/config path)
- What class of cases it affects
- Implementation status

---

## Scoring Mitigations

### `bounded_author_scoring`
**Type**: `scorer`
**Status**: proposed
**Location**: `app/domain/references/deduplication/scoring/scorer.py`

Cap the contribution of author overlap to the ES score to prevent large collaboration author lists from dominating the score.

**Affects**: `AUTHOR_SCORE_INFLATION`

---

### `require_min_jaccard_even_when_es_high`
**Type**: `scorer`
**Status**: proposed
**Location**: `app/domain/references/deduplication/scoring/scorer.py`

Require minimum Jaccard threshold (e.g., 0.5-0.6) for HIGH confidence even when ES score is very high.

**Current**: Jaccard >= 0.3 for HIGH confidence
**Proposed**: Jaccard >= 0.5 or 0.6

**Affects**: `AUTHOR_SCORE_INFLATION`, `PAPER_SERIES_PART_CONFUSION`

---

### `bigram_jaccard_scoring`
**Type**: `scorer`
**Status**: proposed
**Location**: `app/domain/references/deduplication/scoring/scorer.py`

Add bigram (2-word sequence) Jaccard similarity to catch word order differences that unigram Jaccard misses.

**Affects**: `PAPER_SERIES_PART_CONFUSION`, title variation cases

---

### `numeric_token_boosting`
**Type**: `scorer`
**Status**: proposed
**Location**: `app/domain/references/deduplication/scoring/scorer.py`

Increase weight of numeric tokens and Roman numerals (Part 1 vs Part 2, Vol I vs Vol II) so differences register as significant.

**Affects**: `PAPER_SERIES_PART_CONFUSION`

---

### `length_ratio_check`
**Type**: `scorer`
**Status**: proposed
**Location**: `app/domain/references/deduplication/scoring/scorer.py`

Flag pairs where title length ratio is extreme (e.g., one title is 3x longer than the other) as likely NOT_DUPLICATE.

**Affects**: `TITLE_TRUNCATION`, false positives

---

### `fix_hardcoded_score_0950`
**Type**: `scorer`
**Status**: open
**Location**: `app/domain/references/deduplication/scoring/scorer.py:232`

Currently returns hardcoded `combined_score=0.95` for all HIGH confidence matches. Should return actual combined score for diagnosability.

```python
# Current (wrong):
if es_score >= 100 and jaccard >= 0.3:
    return ScoringResult(combined_score=0.95, confidence=HIGH, ...)

# Proposed (correct):
if es_score >= 100 and jaccard >= 0.3:
    return ScoringResult(combined_score=actual_combined_score, confidence=HIGH, ...)
```

**Affects**: `SCORING_HARDCODED_OUTPUT`

---

## DOI Mitigations

### `doi_suffix_blacklist`
**Type**: `identifier_trust`
**Status**: proposed
**Location**: TBD (ingestion gate or scorer)

Detect and handle DOI suffixes indicating distinct documents:
- `.s001`, `.s002`, etc. → supplementary materials
- `/v1/review`, `/v2/response`, `/decision` → peer review artifacts
- `/v1/`, `/v2/` → versioned documents

**Policy options**:
1. Filter at ingestion (don't import these DOIs)
2. Treat as always NOT_DUPLICATE even if title matches
3. Link to parent DOI and mark as supplementary

**Affects**: `DOI_SUFFIX_SUPPLEMENT`, `DOI_SUFFIX_PEER_REVIEW`, `DOI_SUFFIX_VERSION`

---

### `strict_then_permissive_doi_cleanup`
**Type**: `identifier_cleanup`
**Status**: proposed
**Location**: `app/domain/references/deduplication/` or identifier normalization module

Two-pass DOI normalization:
1. **Stage 1 (fast path)**: Check if DOI already passes strict SDK pattern validation
2. **Stage 2 (cleanup)**: Apply permissive cleanup and re-validate

**Cleanup operations (in order)**:
1. Unescape HTML entities (`&amp;` → `&`, `&gt;` → `>`, `&#x03B1;` → `α`)
2. Strip URL query parameters (remove `?utm_campaign=...`, `?journalcode=...`)
3. Strip URL fragments (remove `#article-info`, `#page=5`, preserve trailing `#` alone)
4. Strip HTML tag remnants (e.g., `"&gt;10.1234/...&lt;/a&gt`)
5. Strip escaped newlines (`\n`, `\\n`)
6. Trim whitespace

**Implementation**: See `/Users/jaybea/dedup_validation/dedup_lab/scripts/analysis/doi_validation.py` for reference implementation. Tested on 20k+ OpenAlex malformed DOIs with 98.9% recovery rate.

**Affects**: `MALFORMED_DOI_RECOVERABLE`

---

### `doi_validation_robot_task`
**Type**: `robot_task`
**Status**: proposed
**Location**: `app/domain/robots/tasks/` or background task queue

When a DOI fails strict validation but passes cleanup:
1. Document the malformed DOI and cleanup actions in a review queue
2. Optionally: resolve DOI via doi.org or Crossref API to verify it's real
3. Flag for human review if resolution fails (phantom DOI)

**Implementation approach**:
- Create `RobotTaskType.VALIDATE_DOI` task
- Input: `{doi_raw, doi_cleaned, cleanup_actions, reference_id}`
- Task attempts resolution via Crossref/doi.org
- Output: `{valid: bool, resolution_url: str, metadata: dict}`
- Updates reference with validation status

**Success criteria**: Validates ~20k malformed DOIs from OpenAlex backlog, confirming 98.9% are real DOIs with correct metadata.

**Affects**: `MALFORMED_DOI_RECOVERABLE`

---

### `doi_collision_safety_gate`
**Type**: `identifier_trust`
**Status**: proposed
**Location**: TBD (post-scoring validation)

Flag cases where same DOI points to different titles. Requires human review or rejection.

**Affects**: `DOI_COLLISION_DANGEROUS`

---

### `mark_as_unsearchable_or_require_human_review`
**Type**: `ingest_gate`
**Status**: proposed
**Location**: Ingestion quality gates

For DOIs that fail both strict and permissive validation AND fail external resolution (Crossref/doi.org):
1. Mark record as `UNSEARCHABLE` if DOI is only identifier
2. Queue for human review if other metadata is strong
3. Fallback to ES+Jaccard title-based dedup if title is meaningful

**Policy decision needed**: What to do with phantom DOIs (pass pattern but not registered)?

**Affects**: `MALFORMED_DOI_RECOVERABLE` (the 1.1% unrecoverable subset of the ~20k malformed DOIs, not the corpus)

---

## Title Mitigations

### `generic_title_blocklist`
**Type**: `ingest_gate`
**Status**: proposed
**Location**: Ingestion service or scorer

Maintain list of generic titles that should:
- Never auto-merge without additional metadata match (journal + year + volume)
- Be marked UNSEARCHABLE if no disambiguating metadata

**Blocklist examples**:
- "Book Reviews", "Editorial Board", "Preface", "Announcements"
- "Issue Information", "Frontmatter", "Cardiovascular News"
- "True", "False", "Data Sheet 1.pdf"

**Affects**: `GENERIC_TITLE_NO_METADATA`, `FRONTMATTER_BACKMATTER`

---

### `comment_response_keyword_detection`
**Type**: `post_filter`
**Status**: proposed
**Location**: Scorer or post-processing

Detect comment/response keywords in titles:
- `re:`, `response`, `reply`, `comment`, `erratum`, `corrigendum`
- `correction`, `closure`, `discussion`, `rebuttal`, `retraction`

When detected:
- Require exact DOI match for DUPLICATE status
- Otherwise mark as NOT_DUPLICATE or NEEDS_HUMAN

**Affects**: `COMMENT_RESPONSE_PAIR`, `ERRATUM_CORRIGENDUM_RETRACTION`

---

### `short_title_additional_metadata_required`
**Type**: `scorer`
**Status**: proposed
**Location**: Scorer

For titles < 20 characters, require additional metadata match:
- Journal/venue name match
- Year match (±1)
- Volume/issue match

**Affects**: `GENERIC_TITLE_NO_METADATA`

---

## ES Query Mitigations

### `analyzer_config_v2`
**Type**: `es_analyzer`
**Status**: proposed
**Location**: ES index settings

Update ES analyzer to handle:
- Better punctuation normalization
- HTML/XML tag stripping
- Unicode normalization

**Affects**: `TITLE_PUNCTUATION_ARTEFACTS`, `TITLE_ENCODING_NOISE`

---

### `candidate_query_template_v4`
**Type**: `es_query`
**Status**: proposed
**Location**: Candidate generation query

Updated query template addressing known issues.

**Affects**: `CANDIDATE_GENERATION_ERROR`

---

## Ingestion Mitigations

### `quality_gate_alphanumeric_titles`
**Type**: `ingest_gate`
**Status**: proposed
**Location**: Import service validation

Reject or mark UNSEARCHABLE records where title is primarily:
- Alphanumeric (>50% digits/symbols)
- Filename-like patterns
- URLs or DOIs as titles

**Affects**: `IDENTIFIER_LIKE_TITLE`

---

### `require_minimum_metadata`
**Type**: `ingest_gate`
**Status**: proposed
**Location**: Import service validation

Require minimum metadata for searchability:
- Title (non-empty, non-generic)
- Year OR DOI

**Affects**: `MISSING_TITLE`, `MISSING_YEAR`

---

## Infrastructure Mitigations

### `increase_http_streaming_timeout`
**Type**: `ops`
**Status**: open
**Location**: `app/domain/imports/service.py:229`

Increase httpx client timeout for large JSONL file streaming from MinIO:

```python
# Current:
async with client.stream("GET", str(import_batch.storage_url)) as response:

# Options:
# 1. Increase timeout
# 2. Implement chunked/resumable downloads
# 3. Add retry logic
# 4. Download file locally before processing
```

**Affects**: `INGESTION_STREAMING_TIMEOUT`

---

### `implement_resumable_import`
**Type**: `ops`
**Status**: proposed
**Location**: Import service

Implement checkpoint/resume for large imports so streaming failures don't lose all progress.

**Affects**: `INGESTION_STREAMING_TIMEOUT`

---

## How to Add a New Mitigation

1. Choose a clear, descriptive ID (lowercase_with_underscores)
2. Specify type: `scorer`, `ingest_gate`, `identifier_cleanup`, `identifier_trust`, `es_query`, `es_analyzer`, `post_filter`, `ops`
3. Set status: `proposed`, `open`, `in_progress`, `implemented`, `rolled_out`, `reverted`
4. Document what it does and where it lives
5. List affected case types
6. Add code snippets for concrete mitigations
