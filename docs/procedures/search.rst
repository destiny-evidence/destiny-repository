Search
======

.. contents:: Table of Contents
    :depth: 3
    :local:


Search Procedures
-----------------

.. _search-procedure:

API Query String Search
^^^^^^^^^^^^^^^^^^^^^^^

The simplest API interface for searching references is the `query string search <https://destiny-repository-prod-app.politesea-556f2857.swedencentral.azurecontainerapps.io/redoc#tag/search/operation/search_references_v1_references_search__get>`_ at `/v1/references/search/`. This endpoint requires :doc:`authentication <oauth>`.

Parameters
""""""""""

The only required parameter is the query string ``q``. Additional optional parameters can be provided to filter, sort, and page through results.

Query String (required)
_____________________________

The ``q`` parameter is a query string in the `Lucene syntax <https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-query-string-query.html#query-string-syntax>`_.

At it's simplest, this can be a simple keyword search, which will search over ``title`` and ``abstract``:

.. code-block::

    # Get references with "climate change" anywhere in the title or abstract:
    ?q=climate change

    # Get references with both "climate change" and "health" anywhere in the title or abstract:
    ?q=climate change AND health

.. note::
    Query parameters must be `URL-encoded <https://www.w3schools.com/tags/ref_urlencode.ASP>`_. For example, spaces must be encoded as ``%20`` or ``+``. Most HTTP client libraries will do this automatically.

More complex queries can be constructed using the search syntax and the set of :ref:`searchable fields <search-fields>`.

.. code-block::

    # Get references with "climate", "climatology" etc in the title and either "John Doe" or "Jane Smith" as an author:
    ?q=title:"climat*" AND authors:("John Doe" OR "Jane Smith")

    # Get references with "adaptation" or "mitigation" in the abstract that haven't yet been classified against the `Intervention` taxonomy:
    ?q=abstract:(adaptation OR mitigation) AND NOT evaluated_schemes:classification:taxonomy:Intervention

    # Get references with "climate change" in any order and a typoed "health":
    ?q="change climate"~2 AND helth~

Start Year and End Year
__________________________________________________

The minimum and maximum publication years (inclusive) for references to return.

.. code-block::

    # Get references published from 2015 onwards:
    ?q=...&start_year=2015

    # Get references published up to and including 2020:
    ?q=...&end_year=2020

    # Get references published from 2015 to 2020:
    ?q=...&start_year=2015&end_year=2020

Annotations
__________________________

The ``annotation`` parameter can be used to filter results based on their annotations.

These are provided in the format ``<scheme>[/<label>][@score]``.

- If an annotation is provided without a score, results will be filtered for that annotation being true
- If a score is specified, results will be filtered for that annotation having a score greater than or equal to the given value.
- If the label is omitted, results will be filtered if any annotation with the given scheme is true.

Multiple annotations can be provided; they will be combined using a logical ``AND``.

.. code-block::

    # Get references annotated with `classification:taxonomy:Outcomes/Stroke` as true:
    ?q=...&annotation=classification:taxonomy:Outcomes/Stroke

    # Get references with an inclusion:destiny score of at least 0.8:
    ?q=...&annotation=inclusion:destiny@0.8

    # Get references annotated with `classification:taxonomy:Outcomes/Stroke` as true and inclusion:destiny as true:
    ?q=...&annotation=classification:taxonomy:Outcomes/Stroke&annotation=inclusion:destiny

Concepts
__________________________

The ``concept`` parameter filters results by their linked-data concept URIs (matched against the ``linked_data_concepts`` field).

- Each ``concept`` value is a fully-qualified concept URI, or a comma-separated list of URIs.
- Within a single ``concept`` value, URIs are combined using a logical ``OR`` - a reference matches if it carries any one of them.
- Multiple ``concept`` parameters are combined using a logical ``AND`` - a reference must match each one.

.. code-block::

    # Get references annotated with the C00001 concept:
    ?q=...&concept=https://vocab.evidence-repository.org/scheme/C00001

    # Get references annotated with either the C00001 or C00002 concept:
    ?q=...&concept=https://vocab.evidence-repository.org/scheme/C00001,https://vocab.evidence-repository.org/scheme/C00002

    # Get references annotated with (C00001 OR C00002) AND a third concept:
    ?q=...&concept=https://vocab.evidence-repository.org/scheme/C00001,https://vocab.evidence-repository.org/scheme/C00002&concept=https://vocab.evidence-repository.org/scheme/C00003

Countries
__________________________

The ``country`` parameter filters results by ISO 3166-1 alpha-2 country codes.

- Each ``country`` value is a single code, or a comma-separated list of codes.
- Within a single value, codes are combined using ``OR``; multiple ``country`` parameters AND.
- Codes are validated for shape only (two letters) and uppercased on input — e.g. ``us`` and ``US`` both pass through. Codes that don't match the ``[A-Z]{2}`` shape return ``400``.

.. code-block::

    # Get references tagged with the United States:
    ?q=...&country=US

    # Get references tagged with the United States, the UK, or France:
    ?q=...&country=US,GB,FR

    # Get references tagged with (US OR GB) AND (FR OR DE):
    ?q=...&country=US,GB&country=FR,DE

World Bank Regions
__________________________

The ``country_wb_region`` parameter filters results by World Bank region IDs.

- Each value is a single region ID, or a comma-separated list of IDs.
- Within a single value, IDs are combined using ``OR``; multiple parameters AND.
- IDs come from a closed set: ``EAS``, ``ECS``, ``LCN``, ``MEA``, ``NAC``, ``SAS``, ``SSF``. Unknown IDs return ``400``.

.. code-block::

    # Get references tagged with North American countries:
    ?q=...&country_wb_region=NAC

    # Get references tagged with North America or East Asia & Pacific:
    ?q=...&country_wb_region=NAC,EAS

Page
_____________

The page number of results to return. Each page is 20 results.

If omitted, defaults to the first page.

.. code-block::

    # Get the 41st to 60th results:
    ?q=...&page=3

Sort
_____________

The field(s) to sort the results by. Use ``-`` prefix to sort in descending order.

If not provided, defaults to ``relevance`` as scored by the search engine.

Multiple sort fields can be provided; they will be applied in the order given.

.. code-block::

    # Sort by inclusion score ascending:
    ?q=...&sort=inclusion:destiny

    # Sort by publication year descending:
    ?q=...&sort=-publication_year

    # Sort by publication year ascending, then inclusion score descending:
    ?q=...&sort=publication_year&sort=-inclusion:destiny

Returns
"""""""

Returns a :class:`ReferenceSearchResult <libs.sdk.src.destiny_sdk.references.ReferenceSearchResult>` object.

Limitations
"""""""""""

There is a hard cap on the number of results at 10,000. You cannot page past this point, nor will :class:`total <libs.sdk.src.destiny_sdk.search.SearchResultTotal>` show more than this.

.. _facets-procedure:

API Facet Counts
^^^^^^^^^^^^^^^^

The `facets endpoint <https://api.evidence-repository.org/redoc#tag/search/operation/count_facets_for_search_v1_references_search_facets__get>`_ at `/v1/references/search/facets/` returns per-facet term counts across the references matching the search.

Accepts the same filter parameters as `/v1/references/search/` plus one or more ``facet`` values. Only the requested facet types appear in the response.

.. code-block::

    # Count concepts across all references matching a query:
    ?q=climate&facet=concepts

Sibling-aware facet counts
__________________________

When you filter on a field *and* request that field's facet, the bucket counts show what you'd see if your selection were toggled - not the co-occurrence under your filter. The behaviour is OR within a sibling family and AND with everything else.

There are two flavours, distinguished by how siblings are defined:

**Concepts.** A concept's siblings come from the SKOS vocabulary, so ``concept=`` must be supplied alongside ``vocabulary=`` when requesting ``facet=concepts``. Each ``concept=`` parameter is treated as one sibling group.

For example, ``concept=Botany,Zoology`` AND ``concept=Africa`` with ``facet=concepts``:

- The Botany/Zoology group's counts show every Topic concept (Botany, Zoology, Microbiology, …) as if you swapped the selection, with the Africa filter still applied.
- The Africa group's counts show every Region concept (Africa, Asia, Europe, …), with the (Botany OR Zoology) filter still applied.
- An "unselected" bucket surfaces any other concepts present on the matching references.

.. code-block::

    # (Botany OR Zoology) AND Africa, with sibling-aware concept counts.
    ?q=*&concept=https://vocab.evidence-repository.org/Botany,https://vocab.evidence-repository.org/Zoology
        &concept=https://vocab.evidence-repository.org/Africa
        &facet=concepts
        &vocabulary=https://vocab.evidence-repository.org/vocabulary/v1

Restrictions (400 on violation):

1. URIs inside one ``concept=`` must share a sibling set in the vocabulary.
2. Different ``concept=`` filters must have disjoint sibling sets.
3. Every URI must resolve in the supplied vocabulary.

**Countries and WB regions.** There's no vocabulary hierarchy here - the entire field is treated as one sibling family.

.. code-block::

    ?q=*&country=KE&facet=countries

Restrictions (400 on violation):

1. Only a single OR'd filter is supported when requesting the facet counts.

Returns
""""""""""

Returns a :class:`ReferenceFacetResult <libs.sdk.src.destiny_sdk.references.ReferenceFacetResult>` object. Each bucket's count is "references matching if you toggled this value's selection state and left everything else alone."

Limitations
""""""""""""

Each facet returns at most ``ES_AGGREGATION_MAX_BUCKETS`` buckets (default 1000). For concept facets, if a sibling group's vocabulary set exceeds this the request is refused rather than silently truncated.

.. _lookup-procedure:

API Lookup
^^^^^^^^^^

Though not strictly a `search`, the `lookup endpoint <https://destiny-repository-prod-app.politesea-556f2857.swedencentral.azurecontainerapps.io/redoc#tag/v1/operation/lookup_references_v1_references__get>`_ at `/v1/references/` can be used to retrieve references by their identifiers. This endpoint requires :doc:`authentication <oauth>`.

Parameters
""""""""""

Identifiers (required)
____________________________________

The identifier(s) to look up. Multiple identifiers can be provided, either in a comma-separated list or as multiple parameters.

Identifiers are in the format ``[[<other>:]<type>:]<identifier>``:

- If looking up a reference by its Destiny UUID id, no type prefix is needed: ``09547790-7dfe-455e-a8df-5dca91963a5b``.
- If looking up a reference by a supported :class:`identifier type <libs.sdk.src.destiny_sdk.identifiers.ExternalIdentifierType>`, the type must be prefixed: ``doi:10.1000/xyz123``.
- If looking up a reference by a custom identifier type, the type must be prefixed with ``other:``: ``other:custom:internal-id-001``.


Returns
"""""""

Returns a list of :class:`Reference <libs.sdk.src.destiny_sdk.references.Reference>` objects in :ref:`deduplicated <deduplicated-projection>` form.

Limitations
"""""""""""

There is a hard cap of 100 identifiers per request. If more are needed, multiple requests must be made.

.. _search-fields:


Search Fields
-------------

Search Field Selection
^^^^^^^^^^^^^^^^^^^^^^

References may have multiple sources of information, so search fields are collapsed into a single set of searchable fields. The relevant data is prioritised by:

- Fields provided on the :doc:`canonical reference <deduplication>` are prioritised over those on duplicate references.
- Then, the most recently added data is prioritised.


Bibliographic
^^^^^^^^^^^^^

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.title
    :no-index:
    :annotation: str

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.authors
    :no-index:
    :annotation: list[str]

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.publication_year
    :no-index:
    :annotation: int

Abstract
^^^^^^^^

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.abstract
    :no-index:
    :annotation: str

Annotations
^^^^^^^^^^^

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.annotations
    :no-index:
    :annotation: list[str]

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.evaluated_schemes
    :no-index:
    :annotation: list[str]

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.inclusion_destiny
    :no-index:
    :annotation: float[0-1]

Linked Data
^^^^^^^^^^^

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.linked_data_concepts
    :no-index:
    :annotation: list[str]

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.linked_data_labels
    :no-index:
    :annotation: list[str]

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.linked_data_evaluated_properties
    :no-index:
    :annotation: list[str]

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.linked_data_countries
    :no-index:
    :annotation: list[str]

.. autoattribute:: app.domain.references.models.es.ReferenceSearchFieldsMixin.linked_data_country_wb_regions
    :no-index:
    :annotation: list[str]
