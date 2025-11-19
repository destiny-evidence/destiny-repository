API Authentication
==================

.. contents:: Table of Contents
    :depth: 2
    :local:

.. note::

    This document is about API authentication for anyone **except** robots. For robots, refer to :doc:`HMAC Auth <../sdk/hmac-auth>`.

Background
----------

Interaction with the DESTINY Repository API requires first obtaining an authentication token from Azure. This token must then be included in the ``Authorization`` header of each API request.

.. mermaid::

    sequenceDiagram
        actor Client
        participant Azure
        participant API
        Client->>Azure: Request token (client credentials)
        Azure-->>Client: Return access token
        Client->>API: API request with Authorization: Bearer <token>
        API-->>Client: Return requested data

Provisioning
------------

In order to obtain a token from Azure, you will need to be enrolled in our tenant ``JT_AD``. Please reach out if you need access.

Everyone will have ``reference.reader``, but please reach out if you need additional permission scopes. You can see the available scopes per API resource in `the API documentation <https://destiny-repository-prod-app.politesea-556f2857.swedencentral.azurecontainerapps.io/redoc>`_ - it is listed under each sub-category.


Obtaining a token
-----------------

There are a number of ways to obtain an OAuth2 token from Azure.

In all cases, you will need the following information:

.. csv-table:: Authentication Details
    :header: "Environment", "Tenant ID", "Client ID", "Application ID"

    "Development", ``f870e5ae-5521-4a94-b9ff-cdde7d36dd35``, ``0fde62ae-2203-44a5-9722-73e965325ae7``, ``0a4b8df7-5c97-42b2-be07-2bb25e06dbb2``
    "Staging", ``f870e5ae-5521-4a94-b9ff-cdde7d36dd35``, ``96ed941e-15dc-4ec0-b9e7-e4eda99efd2e``, ``14e3f6c0-b8aa-46c6-98d9-29b0dd2a0f7c``
    "Production", ``f870e5ae-5521-4a94-b9ff-cdde7d36dd35``, ``7164ff26-4078-4107-850f-57b43b97f605``, ``e314440e-f72c-4b8e-89c1-7eefef4b55ed``

Using a script
^^^^^^^^^^^^^^

You can obtain a token programmatically using libraries such as `MSAL for Python <https://pypi.org/project/msal/>`_.

This is probably the easiest way.

This might be particularly useful for ad-hoc scripts or notebooks that need to interact with the API.

.. code-block:: python

    from msal import PublicClientApplication

    app = PublicClientApplication(
        client_id="<your-client-id>",
        authority="https://login.microsoftonline.com/<tenant-id>",
        client_credential=None,
    )
    token = app.acquire_token_interactive(
        scopes=["api://<application-id>/.default"]
    )
    access_token = token["access_token"]


Using assumed identities
^^^^^^^^^^^^^^^^^^^^^^^^

If your code is running in an Azure environment, we can use a managed identity to manage the machine-to-machine authentication. Please reach out if this is you and we'll help you set this up.


Using the token
---------------

The API base URL for each environment is as follows:

.. csv-table:: API URLs
    :header: "Environment", "API URL"

    "Development", "https://destiny-repository-deve-app.gentlecoast-c1c9497a.swedencentral.azurecontainerapps.io"
    "Staging", "https://destiny-repository-stag-app.proudmeadow-2a76e8ac.swedencentral.azurecontainerapps.io"
    "Production", "https://destiny-repository-prod-app.politesea-556f2857.swedencentral.azurecontainerapps.io"


When making API requests, include the token in the ``Authorization`` header following ``Bearer``, eg:

.. code-block:: python

    import httpx

    httpx.get(
        api_url + "/v1/references/search/?q=example",
        headers={"Authorization": "Bearer <access_token>"},
    )

The tokens will expire after a certain period (usually two hours). After expiration, you will need to obtain a new token using the same method as before.


Troubleshooting
---------------

Please reach out if you experience any issues both obtaining or using tokens - most likely, we need to update some permissions.
