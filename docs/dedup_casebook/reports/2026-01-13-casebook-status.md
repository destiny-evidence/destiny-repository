# Deduplication Casebook Report

**Generated**: 2026-01-13 | **Branch**: `chore/dedup-casebook` | **Cases**: 12

---

## Executive Summary

The casebook documents **12 concrete failure cases** across **6 taxonomy categories**. The most critical finding is the **~20,000 malformed DOIs from OpenAlex** with a **98.9% recovery rate** via a 6-stage cleanup pipeline.

| Category | Cases | Severity 5 (Critical) | Severity 3-4 | Status |
|----------|-------|----------------------|--------------|--------|
| A. Identifier Problems | 6 | 0 | 5 | All triaged |
| D. False Positives | 4 | 2 | 2 | All open |
| E. Unsearchable Records | 1 | 0 | 0 | Open |
| F. System Issues | 1 | 0 | 1 | Open |

---

## Category A: Identifier Problems (6 cases)

### Malformed DOIs (~20k in OpenAlex)

| Pattern | % of Malformed | Example | Recovery |
|---------|----------------|---------|----------|
| URL query params | 40-50% | `?utm_campaign=email` | Strip after `?` |
| HTML entities | 20-30% | `&amp;` → `&` | Unescape |
| URL fragments | 15-20% | `#article-info` | Strip after `#` |
| Combined cruft | 10-15% | Multiple issues | Sequential cleanup |
| **Phantom/unrecoverable** | **1.1%** | Never registered | Mark UNSEARCHABLE |

**Key stat**: 1.1% of ~20k malformed = ~220 DOIs unrecoverable (not 1.1% of corpus)

### DOI Suffix Semantics (2 cases)

| Suffix Pattern | Example | Policy |
|----------------|---------|--------|
| `.s001`, `.s002` | ACS supplements | Filter or mark NOT_DUPLICATE |
| `/v2/response1`, `/review2` | Peer review artifacts | Filter at ingestion |

---

## Category D: False Positives - The Dangerous Ones (4 cases)

### Severity 5: False Positive Merges

| Case | Problem | Signals | Mitigation |
|------|---------|---------|------------|
| **ATLAS author inflation** | 2900-author list inflates ES score to 2780.1 | Jaccard: 0.12, ES: 2780 | `bounded_author_scoring` |
| **Part I vs Part II** | Roman numerals ignored by Jaccard | Jaccard: 0.95, different content | `numeric_token_boosting` |

**ATLAS case**: Physics collaboration paper matched to *sausage microbiology paper* due to author list size.

### Severity 4: Near-Misses

| Case | Problem | Example |
|------|---------|---------|
| **Comment/Response pairs** | 96% Jaccard, different documents | "Re: Cisplatin..." vs "RESPONSE: Re: Cisplatin..." |
| **Supplement DOIs** | 100% Jaccard (same title), different assets | `10.1021/...` vs `10.1021/....s002` |

---

## Category E & F: System/Operational Issues (2 cases)

| Case | Problem | Impact |
|------|---------|--------|
| **Generic titles** | "Book Reviews" (22x), "Editorial Board" (14x) | Jaccard=1.0 for unrelated journals |
| **Hardcoded 0.950 score** | All HIGH confidence → same score | Can't distinguish 95% vs 99.9% similar |

---

## Key Tensions to Highlight

### 1. DOI Trust Paradox

- DOIs *should* be unique identifiers
- Reality: 29,848 DOIs with multiple Work IDs in OpenAlex
- 20,790 have genuinely different titles (data quality issue upstream)

### 2. Jaccard vs Author-Weighted ES Score

- ES score dominated by author overlap (good for normal papers)
- Fails catastrophically for large collaborations (ATLAS: 2900 authors)
- Current threshold: Jaccard >= 0.3 for HIGH confidence
- ATLAS case had Jaccard = 0.12 but still merged

### 3. Same Title ≠ Same Work

- Supplements share parent title (100% Jaccard)
- Peer review artifacts share manuscript ID
- Generic titles ("Book Reviews") are legitimately repeated

### 4. Cleanup vs Validation

- 98.9% of malformed DOIs are real DOIs with cruft
- Cleanup pipeline works, but needs external validation
- Robot task to verify via doi.org/Crossref API

---

## Proposed Mitigations (Prioritized)

| Priority | Mitigation | Impact | Status |
|----------|-----------|--------|--------|
| **P0** | `strict_then_permissive_doi_cleanup` | Recovers 98.9% of 20k malformed DOIs | Proposed |
| **P0** | `bounded_author_scoring` | Prevents ATLAS-style false positives | Proposed |
| **P1** | `require_min_jaccard_even_when_es_high` | Safety net for high ES scores | Proposed |
| **P1** | `doi_suffix_blacklist` | Filters supplements/peer review | Proposed |
| **P2** | `comment_response_keyword_detection` | Detects "Re:", "RESPONSE:" | Proposed |
| **P2** | `generic_title_blocklist` | "Book Reviews", "Editorial Board" | Proposed |
| **P3** | `fix_hardcoded_score_0950` | Diagnosability improvement | Open |

---

## Numbers at a Glance

```
Total cases documented:        12
Severity 5 (false merges):      2
Severity 4 (false negatives):   3
Severity 3 (near-miss):         5
Severity 2 (edge case):         2

Malformed DOIs (OpenAlex):  ~20,000
  - Recoverable via cleanup:   98.9%
  - Truly phantom:              1.1% (~220 DOIs)

DOI collisions (same DOI, different title): 20,790
Dangerous collisions (merge risk):           3,243
```

---

## Casebook Validation Results

The casebook design goal was **<2 minutes per case**. We added 5 malformed DOI cases in one session, validating the workflow:

1. Copy template JSON
2. Fill in record snapshots from logs/analysis
3. Set expected_relation and observed_relation
4. Link to mitigation IDs (don't repeat solutions)
5. Commit

---

## Test Integration (Next Steps)

The casebook is currently **documentation infrastructure**. To become **testing infrastructure**:

1. **Loader module**: Parse JSON cases into domain objects
2. **Pytest markers**: Map case status to test behavior
   - `status: fixed` → must pass
   - `status: triaged` → xfail (expected failure)
   - `status: wontfix` → skip
3. **Parameterized tests**: Each case becomes a test
4. **CI integration**: Failing cases don't break build (xfail), but fixed mitigations become guardrails

---

## Case Index

| Case ID | Type | Severity | Status |
|---------|------|----------|--------|
| `author_inflation__atlas_001` | AUTHOR_SCORE_INFLATION | 5 | open |
| `paper_series__quantum_hall_part_1_vs_2` | PAPER_SERIES_PART_CONFUSION | 5 | open |
| `comment_response__cisplatin_therapy` | COMMENT_RESPONSE_PAIR | 4 | open |
| `doi_suffix__acs_supplement` | DOI_SUFFIX_SUPPLEMENT | 4 | open |
| `doi_suffix__peer_review_v2` | DOI_SUFFIX_PEER_REVIEW | 3 | open |
| `malformed_doi__url_query_params` | MALFORMED_DOI_RECOVERABLE | 3 | triaged |
| `malformed_doi__html_entities` | MALFORMED_DOI_RECOVERABLE | 3 | triaged |
| `malformed_doi__url_fragments` | MALFORMED_DOI_RECOVERABLE | 3 | triaged |
| `malformed_doi__combined_cruft` | MALFORMED_DOI_RECOVERABLE | 4 | triaged |
| `malformed_doi__phantom_unrecoverable` | MALFORMED_DOI_RECOVERABLE | 2 | wontfix |
| `generic_title__book_reviews` | GENERIC_TITLE_NO_METADATA | 2 | open |
| `scoring__hardcoded_0950` | SCORING_HARDCODED_OUTPUT | 3 | open |