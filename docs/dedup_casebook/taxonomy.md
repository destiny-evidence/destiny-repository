# Deduplication Casebook Taxonomy

## Case Types

Each case must be assigned exactly one `case_type` from the taxonomy below. These types represent known failure modes, edge cases, and system issues discovered during deduplication testing and production use.

### A. Identifier Problems

#### `MALFORMED_DOI_RECOVERABLE`
DOI contains URL encoding, fragments, HTML entities, or other recoverable noise.
- **Policy**: Clean via strict-then-permissive pipeline
- **Examples**: `10.1234%2Ffoo`, `10.1234/foo?param=value#anchor`

#### `DOI_COLLISION_DANGEROUS`
Same DOI points to different titles/content (actual collision or data corruption).
- **Policy**: Safety gate + collision-rate analysis
- **Examples**: Multiple distinct papers with identical DOI

#### `DOI_SUFFIX_SUPPLEMENT`
DOI suffix indicates supplementary material (`.s001`, `.s002`, etc.).
- **Policy**: Treat as distinct document or filter at ingestion
- **Examples**: `10.1021/acs.jproteome.4c00806.s002`

#### `DOI_SUFFIX_PEER_REVIEW`
DOI suffix indicates peer review artifacts (`/v1/review`, `/v2/response`, `/decision`).
- **Policy**: Treat as distinct or filter at ingestion (likely not relevant for evidence synthesis)
- **Examples**: `10.1039/d4nj04926h/v2/response1` vs `/v2/review2`

#### `DOI_SUFFIX_VERSION`
DOI suffix indicates versioning (`/v1/`, `/v2/`, etc.) for same intellectual work.
- **Policy**: Requires policy decision - are these duplicates or distinct?
- **Examples**: `10.1098/rsob.240304/v1/decision1` vs `/v2/decision1`

#### `EXTERNAL_ID_INCORRECT_MAPPING`
Wrong PMID, WID, or other external ID mapping leading to unrelated pairs.
- **Policy**: Validate external ID mappings
- **Examples**: PMID points to different paper than DOI suggests

#### `MISSING_IDENTIFIER_REQUIRED`
Generic/templated titles that require DOI to deduplicate but DOI is missing.
- **Policy**: Mark as UNSEARCHABLE or reject at ingestion
- **Examples**: "Occurrence Download" with no DOI

---

### B. Title/Content Variation (True Duplicates That Look Different)

#### `TITLE_PUNCTUATION_ARTEFACTS`
Tokenization differences, split vs regex, punctuation handling.
- **Policy**: Normalize punctuation consistently
- **Examples**: "COVID-19" vs "COVID 19", "T-cell" vs "T cell"

#### `TITLE_ENCODING_NOISE`
HTML entities, MathML, XML tags, newlines, encoding issues.
- **Policy**: Strip tags/entities, normalize Unicode
- **Examples**: `&lt;i&gt;italic&lt;/i&gt;` vs "italic", `&#x03B1;` vs "α"

#### `TITLE_TRANSLATION_VARIANT`
Same work with titles in different languages or bracketed alternate titles.
- **Policy**: Cross-source variation is expected; may need language detection
- **Examples**: English title vs Japanese title for same paper

#### `TITLE_TRUNCATION`
One source truncates title, reducing Jaccard similarity.
- **Policy**: Fuzzy matching for truncated titles; length ratio check
- **Examples**: Full 200-char title vs 100-char truncated version

#### `PREPRINT_VS_PUBLISHED_DRIFT`
Title changed between preprint (arXiv) and published version.
- **Policy**: Requires multi-signal matching (authors + year + identifiers)
- **Examples**: arXiv title differs from final journal publication

---

### C. Year/Venue Drift

#### `YEAR_DRIFT_SMALL`
±1 year difference (common; online-first vs print, arXiv gap).
- **Policy**: Tolerate ±1 year for otherwise strong matches
- **Examples**: 2023 vs 2024 for same paper

#### `YEAR_DRIFT_ARXIV_GAP`
Large year gap between arXiv preprint and eventual publication.
- **Policy**: May need special arXiv handling
- **Examples**: arXiv 2018, published 2022

#### `MULTI_JOURNAL_PUBLICATION`
Same work legitimately republished in multiple journals.
- **Policy**: Requires human judgment - are these duplicates or distinct citations?
- **Examples**: Position paper in both European Radiology and JACR

---

### D. False Positives (Not Duplicates, High Similarity)

#### `PAPER_SERIES_PART_CONFUSION`
Multi-part papers: "Part I" vs "Part II", "Vol 1" vs "Vol 2", Roman numerals.
- **Policy**: Boost numeric token weight; mark as NOT_DUPLICATE or NEEDS_HUMAN
- **Examples**: "Theory of quantum Hall Smectic Phase. I" vs "...Phase. II"

#### `COMMENT_RESPONSE_PAIR`
Comment/response/reply/erratum/corrigendum to original paper.
- **Policy**: Detect keywords; require DOI match or mark as NOT_DUPLICATE
- **Examples**: "Re: Cisplatin Therapy..." vs "RESPONSE: Re: Cisplatin Therapy..."

#### `ERRATUM_CORRIGENDUM_RETRACTION`
Formal corrections or retractions of papers.
- **Policy**: Link to original but treat as distinct document
- **Examples**: "Erratum to: [original title]"

#### `PEER_REVIEW_ARTEFACT`
Peer review rounds, decisions, author responses as separate DOI objects.
- **Policy**: Likely filter at ingestion; not relevant for evidence synthesis
- **Examples**: "Review for: [paper title]" vs "Author response for: [paper title]"

#### `SUPPLEMENTARY_MATERIAL`
Supporting information, data sheets, supplements as distinct DOIs.
- **Policy**: Link to parent paper or filter at ingestion
- **Examples**: "Data Sheet 1.pdf", "Supplementary Information"

#### `FRONTMATTER_BACKMATTER`
Journal front/back matter with generic titles.
- **Policy**: Blocklist + mark as UNSEARCHABLE
- **Examples**: "Editorial Board", "Preface", "Book Reviews", "Issue Information"

#### `AUTHOR_SCORE_INFLATION`
Large collaboration author lists (ATLAS, CERN, etc.) inflate ES score despite unrelated titles.
- **Policy**: Bounded author scoring + Jaccard safety net
- **Examples**: 2900-author physics paper matched to unrelated 2-author paper

---

### E. Unsearchable/Low-Signal Records

#### `GENERIC_TITLE_NO_METADATA`
Short, generic titles without disambiguating metadata.
- **Policy**: Blocklist + require additional metadata (journal, year, volume)
- **Examples**: "True", "Announcements", "Cardiovascular News"

#### `IDENTIFIER_LIKE_TITLE`
Filenames, URLs, alphanumeric strings as titles.
- **Policy**: Quality gate at ingestion
- **Examples**: "10.1371/journal.pgph.0002664.s002", "image_001.png"

#### `MISSING_YEAR`
Record lacks publication year (if year is required for deduplication).
- **Policy**: Ingestion gate if year is mandatory
- **Examples**: Any record with null/missing year

#### `MISSING_TITLE`
Record lacks title metadata entirely.
- **Policy**: Mark as UNSEARCHABLE
- **Examples**: Supplement DOIs with no title

---

### F. System/Operational Issues

#### `INGESTION_STREAMING_TIMEOUT`
Large file streaming from MinIO/S3 times out, causing partial imports.
- **Policy**: Infrastructure fix (increase timeout, chunked download, retry logic)
- **Examples**: 277MB JSONL file streaming only 8.6MB before connection drops

#### `SCORING_HARDCODED_OUTPUT`
Scoring system returns hardcoded values (e.g., 0.950) instead of actual combined score.
- **Policy**: Fix scorer to return true combined score for diagnosability
- **Examples**: All HIGH confidence matches show `score=0.950` regardless of actual similarity

#### `CANDIDATE_GENERATION_ERROR`
ES query returns unexpected candidates or fails to return obvious candidates.
- **Policy**: Debug ES query, analyzer, or index settings
- **Examples**: Expected candidate not in top-K results

#### `THRESHOLD_CALIBRATION_NEEDED`
Current thresholds (Jaccard, ES score) are too permissive or too strict.
- **Policy**: Adjust thresholds based on empirical false positive/negative rates
- **Examples**: Jaccard >= 0.3 for HIGH confidence is too low

---

## Severity Levels

Each case should be assigned a severity (1-5):

- **5**: False positive merge (wrong papers marked as duplicates)
- **4**: False negative miss (obvious duplicates not found)
- **3**: Dangerous near-miss (would fail if thresholds slightly different)
- **2**: Edge case (correct behavior but worth documenting)
- **1**: Informational (expected behavior, logged for completeness)

---

## Status Values

- `open`: Newly logged, not yet triaged
- `triaged`: Reviewed, mitigation identified
- `fixed`: Mitigation implemented
- `regression_tested`: Test added to prevent recurrence
- `wontfix`: Accepted limitation or out of scope

---

## Expected Relation Values

For pair assertions:

- `DUPLICATE`: These are the same intellectual work
- `NOT_DUPLICATE`: These are distinct works
- `NEEDS_HUMAN`: Automated system cannot decide reliably
- `UNSEARCHABLE`: Record lacks sufficient metadata for deduplication
