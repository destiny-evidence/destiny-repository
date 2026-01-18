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

### Unsafe DOIs for Deduplication

These DOI patterns cause mass collisions and must be skipped during DOI-based deduplication. References with these DOIs fall through to title-based deduplication instead.

| Pattern                   |  Count | Issue                         |
| ------------------------- | -----: | ----------------------------- |
| Funder DOIs (10.13039/\*) |    297 | Crossref Funder Registry DOIs |
| Template DOIs (contain %) | 16,405 | Unresolved placeholder DOIs   |

**Why These DOIs Are Problematic:**

1. **Funder DOIs (10.13039/\*)** are Crossref Funder Registry identifiers assigned to funding organizations (e.g., `10.13039/501100000780` = European Commission). These are NOT paper DOIs. When a paper's DOI field contains a funder DOI, it's data corruption - the publisher incorrectly put the funder's DOI instead of the paper's DOI. If we trust these for deduplication, ALL papers with the same funder DOI would be incorrectly merged as duplicates.

2. **Template DOIs (containing %)** are unresolved URL-encoded placeholders from broken publishing systems (e.g., `10.5007/%x`, `10.1234/%DIFFKEY%`). These represent DOI templates that were never populated with actual identifiers. Multiple unrelated papers share the same template DOI, causing mass false-positive matches.

**Alternative Identifier Availability:**

Query of OpenAlex data shows papers with funder/template DOIs rarely have alternative identifiers:

| DOI Type     | Papers |  Have PMID | Have PMCID |
| ------------ | -----: | ---------: | ---------: |
| Funder DOI   |  3,120 |   6 (0.2%) |          0 |
| Template DOI | 19,300 | 107 (0.6%) |          0 |

This means we cannot easily look up "correct" DOIs via PubMed/PMC crosswalk.

**Remediation Strategy:**

1. **Immediate**: Skip these DOIs during deduplication, fall through to title-based matching
2. **Robot fix**: A robot can attempt to look up correct DOIs via Crossref/OpenAlex API using title/authors. With only ~16K affected records, this is feasible to run as a batch job

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
