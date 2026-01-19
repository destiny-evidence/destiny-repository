# OpenAlex Data Quality Analysis

**Snapshot:** January 2026
**Validated:** 2026-01-18
**Source:** `/Volumes/4TBSSD/openalex/jan2026_works/*.parquet`

## Summary

| Metric        | Count       |
| ------------- | ----------- |
| Total records | 474,001,330 |
| Unique DOIs   | 288,416,485 |

## DOI Quality Analysis

### Issues Requiring Cleanup

| Issue                       |   Count | Percentage |
| --------------------------- | ------: | ---------: |
| Funder DOIs (10.13039/\*)   |     297 |    0.0001% |
| Template DOIs (contain %)   |  16,405 |    0.0057% |
| HTML entities (&amp; etc)   |  61,189 |    0.0212% |
| HTML tags (</...)           |   4,148 |    0.0014% |
| Query params (?...)         | 120,912 |    0.0419% |
| Fragments (#...)            |  48,785 |    0.0169% |
| PDF suffix (/pdf)           | 208,727 |    0.0724% |
| Abstract suffix (/abstract) |   3,269 |    0.0011% |
| Full suffix (/full)         |   2,091 |    0.0007% |
| Session IDs (jsessionid)    |     486 |    0.0002% |
| Tracking params (utm\_)     | 106,639 |    0.0370% |
| Magic params (&magic=)      |   3,302 |    0.0011% |
| URL encoded (%2F etc)       |   7,740 |    0.0027% |

### Valid Special Patterns

| Pattern                      |      Count | Percentage |
| ---------------------------- | ---------: | ---------: |
| SICI-style DOIs (::aid-...>) |    328,893 |    0.1140% |
| DOIs with parentheses        | 10,330,671 |    3.5819% |

**SICI-style DOIs** use a legacy format from Wiley with `#` as a checksum character:

```text
10.1002/1096-8652(200007)64:3<210::aid-ajh13>3.0.co;2-#
```

This `#` is valid and must NOT be stripped.

### Fragment Identifiers (#)

OpenAlex contains two types of `#` in DOIs:

**1. DataCite granular identifiers (valid - keep):**

```text
10.15475/dhz/kfn/1918/7/24#article-93781ded3680878c30a32ce9d62e8e0d
10.15475/dhz/kfn/1915/11/27#page-6
```

These are sub-resource DOIs from DataCite (e.g., German historical newspapers with per-article/per-page DOIs). Identified by `is_xpac: True` in OpenAlex. The fragment points to a specific article or page within a larger work.

**2. URL pollution fragments (invalid - strip):**

```text
10.1007/s00170-021-08362-y#article-info     ← Springer website anchor
10.1186/s12888-020-02511-5#article-info     ← BMC website anchor
10.1007/s11422-011-9339-1?null#page-1       ← query param + fragment
```

These are website navigation anchors accidentally included during DOI extraction. Common patterns: `#article-info`, `#references`, `#abstract`, `#supplementary`.

**Cleanup rule:** Strip `#` fragments EXCEPT for known DataCite granular patterns (`#article-{hash}`, `#page-N` on DataCite prefixes).

### Unsafe DOIs for Deduplication

These DOI patterns cause mass collisions and must be skipped during DOI-based deduplication. References with these DOIs fall through to title-based deduplication instead.

| Pattern                   |      Count | Issue                                                      |
| ------------------------- | ---------: | ---------------------------------------------------------- |
| Funder DOIs (10.13039/\*) |        297 | Crossref Funder Registry DOIs                              |
| Template DOIs (contain %) |     16,405 | Unresolved placeholder DOIs                                |
| W-ID < 40M DOIs           | ~1,111,353 | [PMID/W-ID collision bug](#w-idpmid-doi-misassignment-bug) |

**Why These DOIs Are Problematic:**

1. **Funder DOIs (10.13039/\*)** are Crossref Funder Registry identifiers assigned to funding organizations (e.g., `10.13039/501100000780` = European Commission). These are NOT paper DOIs. When a paper's DOI field contains a funder DOI, it's data corruption - the publisher incorrectly put the funder's DOI instead of the paper's DOI. If we trust these for deduplication, ALL papers with the same funder DOI would be incorrectly merged as duplicates.

2. **Template DOIs (containing %)** are unresolved URL-encoded placeholders from broken publishing systems (e.g., `10.5007/%x`, `10.1234/%DIFFKEY%`). These represent DOI templates that were never populated with actual identifiers. Multiple unrelated papers share the same template DOI, causing mass false-positive matches.

3. **W-ID < 40M DOIs** are affected by an OpenAlex pipeline bug where legacy Work IDs were incorrectly used as PubMed ID lookup keys. Since W-ID 1901568 ≠ PMID 1901568, every DOI on these ~1.1M records belongs to a completely different paper. See [W-ID/PMID DOI Misassignment Bug](#w-idpmid-doi-misassignment-bug) for details.

**Alternative Identifier Availability:**

Query of OpenAlex data shows papers with funder/template DOIs rarely have alternative identifiers:

| DOI Type     | Papers |  Have PMID | Have PMCID |
| ------------ | -----: | ---------: | ---------: |
| Funder DOI   |  3,120 |   6 (0.2%) |          0 |
| Template DOI | 19,300 | 107 (0.6%) |          0 |

This means we cannot easily look up "correct" DOIs via PubMed/PMC crosswalk.

**Remediation Strategy:**

1. **Funder DOIs**: Discard DOI if prefix is `10.13039/` (automated)
2. **Template DOIs**: Discard DOI if it contains `%` (automated)
3. **W-ID bug DOIs**: Check against pre-computed list of ~554K confirmed buggy W-IDs (see [W-ID/PMID DOI Misassignment Bug](#w-idpmid-doi-misassignment-bug))

Records with discarded DOIs fall through to title-based deduplication. The OpenAlex W-ID remains available for matching against other OpenAlex imports.

## Title Quality Analysis

| Issue                         |      Count | Percentage |
| ----------------------------- | ---------: | ---------: |
| Missing/empty titles          |  7,866,024 |    1.6595% |
| Very short titles (≤10 chars) | 20,998,068 |    4.4300% |
| Titles with HTML/entities     |  9,678,616 |    2.0419% |

### High Collision Risk Titles

These generic titles appear across many records and require careful handling during deduplication:

| Title                       |     Count |
| --------------------------- | --------: |
| Occurrence Download         | 3,962,988 |
| archive.org Member          |   811,802 |
| Introduction                |   464,758 |
| Editorial Board             |   342,554 |
| Streptomyces sp.            |   297,447 |
| Index                       |   268,154 |
| Animalia                    |   257,101 |
| Editorial                   |   255,721 |
| Front Matter                |   241,443 |
| Frontmatter                 |   202,519 |
| Preface                     |   198,757 |
| Table of Contents           |   197,435 |
| Contents                    |   187,767 |
| Lepidoptera Linnaeus, 1758  |   173,427 |
| NBC News Scripts            |   127,072 |
| Book Reviews                |   119,133 |
| Conclusion                  |   113,393 |
| Bibliography                |   104,535 |
| Notes                       |   103,849 |
| Masthead                    |    97,935 |
| Issue Information           |    96,057 |
| Back Matter                 |    87,779 |
| Acknowledgments             |    85,752 |
| The APPLAUSE Data Release 2 |    84,746 |
| Erratum                     |    75,825 |
| Contributors                |    73,027 |
| Foreword                    |    72,491 |
| References                  |    65,988 |
| Einleitung                  |    60,894 |
| Inhalt                      |    54,200 |

## Publication Year Analysis

| Issue                             |      Count | Percentage |
| --------------------------------- | ---------: | ---------: |
| Missing publication_year          | 26,786,884 |    5.6512% |
| Suspicious years (<1500 or >2026) |     16,371 |    0.0035% |

### Suspicious Year Distribution

| Year | Count |
| ---- | ----: |
| 1400 | 2,914 |
| 1480 | 1,424 |
| 1111 | 1,227 |
| 1493 | 1,180 |
| 2027 | 1,144 |
| 1497 | 1,108 |
| 1299 | 1,074 |
| 1499 |   996 |
| 1498 |   948 |
| 1495 |   768 |
| 1491 |   766 |
| 1494 |   762 |
| 1492 |   700 |
| 1490 |   687 |
| 1496 |   673 |

## OpenAlex ID Analysis

| Issue               | Count |
| ------------------- | ----: |
| NULL or empty IDs   |     1 |
| Non-standard format |     0 |
| Duplicate W-IDs     |     0 |

## W-ID/PMID DOI Misassignment Bug

**Severity:** Critical
**Affected Records:** ~553,674 confirmed buggy (of ~964K W-ID < 35M with DOIs)
**Upper Bound:** W35,102,708 (last confirmed buggy W-ID)
**Status:** Aspirational - requires pre-computed correction list
**Origin:** Legacy MAG (Microsoft Academic Graph) records inherited by OpenAlex

### Description

Legacy MAG works with low W-IDs have DOIs incorrectly assigned from PubMed articles where PMID equals the W-ID numerically. These are early MAG records (created ~2016) that were corrupted during DOI enrichment.

### Root Cause

OpenAlex DOI enrichment incorrectly used the numeric W-ID as a PubMed lookup key:

```text
W{X} (e.g., W1901568)
  → Query PubMed: "What's the DOI for PMID {X}?"
  → PubMed returns DOI for PMID 1901568 (a completely different paper)
  → Wrong DOI assigned to W1901568
```

**The telltale sign:** For affected records, the DOI resolves to a paper whose PMID equals the W-ID number.

### Why 40M Threshold

- PubMed IDs (PMIDs) cap at ~40 million
- W-IDs above 40M cannot numerically match any PMID
- Only low W-IDs (legacy records) are affected

### Example

| Field           | W1901568 (OpenAlex)             | PMID 1901568 (PubMed)             |
| --------------- | ------------------------------- | --------------------------------- |
| Title           | "Spanish archival records..."   | "Bacillus subtilis competence..." |
| DOI in OpenAlex | 10.1128/jb.173.6.1867-1876.1991 | (correct for PubMed record)       |
| Actual DOI      | None                            | 10.1128/jb.173.6.1867-1876.1991   |

The Spanish archival work has the Bacillus subtilis paper's DOI because 1901568 = 1901568.

### Verification

**Validated 2026-01-19:** Cross-referenced OpenAlex W-ID < 40M records against PubMed:

1. Joined OpenAlex records (W-ID < 40M with DOIs) to PubMed where PMID = W-ID number
2. Found DOI matches with completely different titles:
   - W10563742: OA="A System Call Tracer for UNIX" → DOI points to PM="Nosocomial infections due to Stenotrophmonas"
   - W10563622: OA="Spray Pyrolysis Deposition..." → DOI points to PM="Childhood-onset epilepsy..."
3. OpenAlex `created_date` = 2016-06-24 for these records (early MAG era)

**Conclusion:** These are legitimate early works that were corrupted by DOI enrichment, NOT W-IDs created from PMIDs. The works existed first; wrong DOIs were assigned later.

- 15/30 sampled records had same DOI but completely different titles (50% visible mismatch rate)
- Reproducible: `uv run python -m tools.source_quality.analyze_work_ids`

### Mitigation

**Targeted approach (not blanket filter):** Pre-compute list of confirmed buggy W-IDs and filter only those at import time.

Why not blanket W-ID < 40M filter:

- ~964K records have W-ID < 35M with DOIs
- Only ~554K (57.5%) are confirmed buggy
- ~410K (42.5%) may have legitimate DOIs from other sources

**Pre-import step:** Generate correction list by joining OpenAlex to PubMed:

```sql
-- Confirmed buggy: OA DOI matches PubMed DOI for PMID = W-ID
SELECT wid_num
FROM openalex_works oa
JOIN pubmed pm ON CAST(REPLACE(oa.id, 'W', '') AS VARCHAR) = pm.pmid
WHERE oa.doi = pm.doi  -- DOI match = bug confirmed
  AND CAST(REPLACE(oa.id, 'W', '') AS BIGINT) <= 35102708  -- Last confirmed buggy W-ID
```

**At import time:** Check against pre-computed set of ~554K buggy W-IDs.

### References

- Source Quality Registry: `registry.yaml` (`openalex_wid_pmid_doi_bug`)
- Casebook Taxonomy: `.casebook/docs/taxonomy.md` (`OPENALEX_WID_PMID_DOI_BUG`)

## Post-Ingestion Data Cleanup

When OpenAlex data is ingested unmodified, the following cleanup can be applied directly to the database.

### DOI Cleanup (SQL)

Most DOI issues can be fixed with PostgreSQL regex operations:

```sql
-- Preview DOIs that would be cleaned
WITH cleaned AS (
  SELECT
    id,
    identifier AS original,
    TRIM(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          REGEXP_REPLACE(
            REGEXP_REPLACE(
              REGEXP_REPLACE(
                REGEXP_REPLACE(
                  REGEXP_REPLACE(
                    REPLACE(REPLACE(REPLACE(identifier, '&amp;', '&'), '&lt;', '<'), '&gt;', '>'),
                    '^(https?://(dx\.)?doi\.org/|doi:)', '', 'i'
                  ),
                  '</\w+.*$', ''
                ),
                '[?#].*$', ''
              ),
              ';jsessionid=[^&]*', '', 'i'
            ),
            '&(magic|prog|utm)[^&]*.*$', '', 'i'
          ),
          '/(abstract|full|pdf|epdf|summary)$', '', 'i'
        ),
        '[.,;\]"'']+$', ''
      )
    ) AS cleaned
  FROM linked_external_identifiers
  WHERE identifier_type = 'doi'
)
SELECT * FROM cleaned WHERE original != cleaned LIMIT 100;

-- Apply the cleanup
UPDATE linked_external_identifiers lei
SET identifier = TRIM(
  REGEXP_REPLACE(
    REGEXP_REPLACE(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          REGEXP_REPLACE(
            REGEXP_REPLACE(
              REGEXP_REPLACE(
                REPLACE(REPLACE(REPLACE(identifier, '&amp;', '&'), '&lt;', '<'), '&gt;', '>'),
                '^(https?://(dx\.)?doi\.org/|doi:)', '', 'i'
              ),
              '</\w+.*$', ''
            ),
            '[?#].*$', ''
          ),
          ';jsessionid=[^&]*', '', 'i'
        ),
        '&(magic|prog|utm)[^&]*.*$', '', 'i'
      ),
      '/(abstract|full|pdf|epdf|summary)$', '', 'i'
    ),
    '[.,;\]"'']+$', ''
  )
)
WHERE identifier_type = 'doi'
  AND identifier != TRIM(
    REGEXP_REPLACE(
      REGEXP_REPLACE(
        REGEXP_REPLACE(
          REGEXP_REPLACE(
            REGEXP_REPLACE(
              REGEXP_REPLACE(
                REGEXP_REPLACE(
                  REPLACE(REPLACE(REPLACE(identifier, '&amp;', '&'), '&lt;', '<'), '&gt;', '>'),
                  '^(https?://(dx\.)?doi\.org/|doi:)', '', 'i'
                ),
                '</\w+.*$', ''
              ),
              '[?#].*$', ''
            ),
            ';jsessionid=[^&]*', '', 'i'
          ),
          '&(magic|prog|utm)[^&]*.*$', '', 'i'
        ),
        '/(abstract|full|pdf|epdf|summary)$', '', 'i'
      ),
      '[.,;\]"'']+$', ''
    )
  );
```

**SQL Limitations:**

- No URL decoding (`%2F` → `/`) - requires Python or extension
- No balanced parentheses check for trailing `)` - use Python for edge cases
- No DOI extraction from surrounding text

### Identify Unsafe DOIs (SQL)

Find references with funder or template DOIs that should not be trusted for DOI-based deduplication:

```sql
-- Find references with funder DOIs (10.13039/*)
-- These are Crossref Funder Registry DOIs, not paper DOIs
SELECT lei.reference_id, lei.identifier, 'funder_doi' as issue
FROM linked_external_identifiers lei
WHERE lei.identifier_type = 'doi'
  AND lei.identifier LIKE '10.13039/%';

-- Find references with template DOIs (contain % placeholders)
-- These are unresolved placeholder DOIs shared by multiple papers
SELECT lei.reference_id, lei.identifier, 'template_doi' as issue
FROM linked_external_identifiers lei
WHERE lei.identifier_type = 'doi'
  AND lei.identifier LIKE '%\%%';
```

Note: DOI cleanup and safety filtering now happens at import time. These queries are for data quality monitoring of legacy data only.

### Full Cleanup with Python (Batch Job)

For cleaning legacy data (imported before DOI cleanup was added), use a Python batch job:

```python
from app.domain.references.models.validators import clean_doi, is_doi_safe_for_dedup

async def batch_cleanup_dois(session, batch_size=10000):
    """Clean all DOIs in the database using the full Python implementation."""
    offset = 0
    while True:
        # Fetch batch of DOI identifiers
        result = await session.execute(
            select(LinkedExternalIdentifier)
            .where(LinkedExternalIdentifier.identifier_type == 'doi')
            .offset(offset).limit(batch_size)
        )
        identifiers = result.scalars().all()
        if not identifiers:
            break

        for ident in identifiers:
            # Clean DOI
            cleanup = clean_doi(ident.identifier)
            if cleanup.was_modified:
                ident.identifier = cleanup.cleaned

            # Check if unsafe - could null out or flag for review
            is_safe, reason = is_doi_safe_for_dedup(ident.identifier)
            if not is_safe:
                ident.identifier = None  # Or flag for review

        await session.commit()
        offset += batch_size
```

### Recommended Cleanup Order (Legacy Data)

1. **DOI Cleanup (SQL)** - Fast, handles 99% of cases
2. **Identify Unsafe DOIs (SQL)** - Find funder/template DOIs for review
3. **Python Batch (optional)** - Handle edge cases (URL decoding, balanced parens)
4. **Re-run Deduplication** - For affected references

Note: New imports automatically clean and filter DOIs at import time via `ExternalIdentifierParseResult._preprocess_doi()`.

## Implications for Deduplication

1. **DOI Cleanup**: The `clean_doi()` function (in `validators.py`) handles URL prefixes, query params, fragments, HTML entities, and trailing punctuation. ~0.16% of DOIs require cleanup.

2. **DOI Safety Filtering**: Funder DOIs and template DOIs are filtered at import time via `is_doi_safe_for_dedup()` to prevent false positive matches. These DOIs are skipped entirely (not stored).

3. **Title Tokenization**: Unicode-aware tokenization handles CJK, Cyrillic, and other non-Latin scripts correctly.

4. **Short Title Handling**: Titles with ≤2 tokens require near-exact Jaccard match to prevent collision-prone titles like "Editorial" from causing false positives.

5. **High Collision Titles**: Titles like "Occurrence Download" (3.9M records) and "Introduction" (464K records) require additional metadata matching (year, authors) to prevent false duplicates.
