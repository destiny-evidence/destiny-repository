.. _search-enhancement-procedure:

Requesting Enhancements from a Search
=====================================

.. note:: This document is best understood in conjunction with :ref:`Robots Schemas <sdk_schemas:Robots>`. The schemas cross-referenced here have significant supplementary documentation.

.. contents:: Table of Contents
    :depth: 2
    :local:

The search enhancement request procedure allows you to request enhancements for every reference matching a search.

Requesting
----------

The ``POST /enhancement-requests/search/`` endpoint accepts four parameters:

- A :ref:`search query string <query-string>`. References matching this query will be requested for enhancement.
- A robot ID. This is the robot that will be used to create the enhancements.
- A dry run flag. When ``True``, the number of matches will be returned and the request will not be submitted.
- An optional source label. This should describe the context for which the enhancements are being requested.

.. note:: A dry run counts every matching reference exactly, so for broad queries it can take noticeably longer than the request itself, which occurs in the background.

Once the request is submitted, the search will run in the background and the repository will request enhancements for every matching reference.

We recommend using the :doc:`SDK <../sdk/sdk>` to make these requests, though the `underlying API <https://api.evidence-repository.org/redoc#tag/search-enhancement-requests>`_ is also available.



Tracking Progress
-----------------

While the processing occurs in the background, the ``GET /enhancement-requests/search/{request_id}/`` endpoint allows you to poll to see progress of the search and the ensuing enhancements.

Both phases of the process are tracked in the response:

- The search phase is tracked by the ``search_status`` and ``n_enhancements_requested`` fields. These allow you to see the progress of the search itself and its requesting of enhancements for the matching references.
- The enhancement fulfillment phase is tracked by the ``request_status`` field. This allows you to see the progress of the underlying robot in creating the requested enhancements.

.. seealso::
    :class:`SearchEnhancementRequestRead <libs.sdk.src.destiny_sdk.robots.SearchEnhancementRequestRead>`


SDK Example Usage
-----------------

See also: :meth:`request_search_enhancement <libs.sdk.src.destiny_sdk.client.OAuthClient.request_search_enhancement>` and :meth:`get_search_enhancement_request <libs.sdk.src.destiny_sdk.client.OAuthClient.get_search_enhancement_request>`.

Preview how many references a query matches, without creating anything:

.. code-block:: python

    from destiny_sdk.client import OAuthClient

    client = OAuthClient(env="production")

    total = client.request_search_enhancement(
        robot_id="<robot-uuid>",
        search_query='title:"climate change" AND abstract:health',
        dry_run=True,
        timeout=120,
    )
    print(f"{total.count} references would have enhancements requested")

Submit the request and track its progress:

.. code-block:: python

    from destiny_sdk.client import OAuthClient

    client = OAuthClient(env="production")

    request = client.request_search_enhancement(
        robot_id="<robot-uuid>",
        search_query='title:"climate change" AND abstract:health',
        source="destiny-sdk docs example",
    )
    print(request.id, request.search_status)

    # Check request status
    status = client.get_search_enhancement_request(request.id)
    print("Search state: ", status.search_status)
    print("Searching progress: ", status.n_enhancements_requested, "of", status.n_matched)
    print("Enhancement fulfillment status: ", status.request_status)
    print("Enhancement fulfillment details: ", status.enhancement_status_counts)


Flow
----

.. mermaid::

    sequenceDiagram
        actor User
        participant Data Repository
        participant Robot
        opt Preview count
            User->>Data Repository: POST /enhancement-requests/search/?dry_run=true : SearchEnhancementRequestIn
            Data Repository-->>User: SearchResultTotal (count)
        end
        User->>Data Repository: POST /enhancement-requests/search/ : SearchEnhancementRequestIn
        Data Repository-->>Data Repository: Register search enhancement request
        Note over Data Repository: search_status: PENDING
        Data Repository-->>User: SearchEnhancementRequestRead (id, search_status)
        Data Repository-->>Data Repository: Scan search & request enhancements
        Note over Data Repository: search_status: SEARCHING -> COMPLETED
        loop Until all fulfilled
            Data Repository-)Robot: Requested enhancements become available
            Robot--)Data Repository: Fulfil enhancements
        end
        Note over Data Repository: request_status: PROCESSING -> COMPLETED
        loop Until terminal
            User->>Data Repository: GET /enhancement-requests/search/<id>/
            Data Repository-->>User: SearchEnhancementRequestRead (progress)
        end
