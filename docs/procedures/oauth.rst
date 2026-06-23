API Authentication
==================

.. contents:: Table of Contents
    :depth: 2
    :local:

.. note::

    This document is about API authentication for anyone **except** robots. For robots, refer to :doc:`HMAC Auth <../sdk/robot-client>`.

Quickstart
----------

For Python users, the quickest way to get started is with the :doc:`SDK <../sdk/client>`, which will handle authentication for you. Just create a client with the appropriate environment and you're good to go:

.. code-block:: python

    # Requires destiny-sdk>=0.12.0
    from destiny_sdk.client import OAuthClient
    client = OAuthClient(env="staging")
    response = client.search(query="example")
    print(response)

Read on for the underlying OAuth2 flow, alternative authentication methods (Postman, curl, service accounts), and overriding configuration.


Background
----------

Interaction with the DESTINY Repository API requires first obtaining an authentication token from the DESTINY authentication server (a `Keycloak <https://www.keycloak.org/>`_ instance). This token must then be included in the ``Authorization`` header of each API request.

.. mermaid::

    sequenceDiagram
        actor Client
        participant Auth Server
        participant API
        Client->>Auth Server: Request token (client credentials)
        Auth Server-->>Client: Return access token
        Client->>API: API request with Authorization: Bearer <token>
        API-->>Client: Return requested data

Provisioning
------------

In order to obtain a token from the DESTINY authentication server, you will need to be enrolled in our auth server. Please reach out if you need access.

Everyone will have ``reference.reader``, but please reach out if you need additional permission scopes. You can see the available scopes per API resource in `the API documentation <https://api.evidence-repository.org/redoc>`_ - it is listed under each sub-category.


Obtaining a token
-----------------

Interactive user authentication
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For human users logging in with their own credentials. Uses the OAuth 2.0 authorization code flow with PKCE; the user is redirected to a browser to authenticate.

Using the SDK
"""""""""""""

This is the recommended way to obtain tokens, as the :doc:`SDK <../sdk/client>` will handle token caching and refreshing for you, and will be kept up to date with any changes to the API authentication process.

The only information you need to authenticate is the environment you want to access (development, staging, or production). Other configuration is overwritable but will default to the correct values for each environment.

.. code-block:: python

    from destiny_sdk.client import OAuthMiddleware

    auth = OAuthMiddleware(env="production")

See :class:`OAuthMiddleware <libs.sdk.src.destiny_sdk.client.OAuthMiddleware>` for the full set of configuration options.

Using another method
""""""""""""""""""""

If you are not using Python, or want to authenticate from a tool like Postman, you can drive Keycloak's OAuth 2.0 authorization code flow with PKCE directly. The values below configure any standards-compliant OAuth 2.0 client.

.. csv-table:: Keycloak Configuration
    :header: "Field", "Value"

    "Authorization endpoint", ``https://auth.evidence-repository.org/realms/destiny/protocol/openid-connect/auth``
    "Token endpoint", ``https://auth.evidence-repository.org/realms/destiny/protocol/openid-connect/token``
    "Realm", ``destiny``
    "Client ID (development)", ``destiny-auth-client-development``
    "Client ID (staging)", ``destiny-auth-client-staging``
    "Client ID (production)", ``destiny-auth-client-production``
    "Grant type", "Authorization Code (with PKCE)"
    "Code challenge method", ``S256``
    "Default scopes", ``openid profile email``

The redirect URI you supply must be registered on the Keycloak client. At present we allow localhost and postman redirect URIs, but if you want to use a different one, please reach out so we can add it.

Service-to-service authentication
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

For backend services, scheduled jobs, or anything else that runs without a human user. Uses the OAuth 2.0 client credentials flow. This requires a dedicated Keycloak client with Service Accounts enabled — please reach out so we can provision one. Scopes for these clients are mapped from service account roles in Keycloak, not group membership.

Using the SDK
"""""""""""""

.. code-block:: python

    from pydantic import SecretStr
    from destiny_sdk.client import OAuthMiddleware

    auth = OAuthMiddleware(
        client_id="my-service-client",
        client_secret=SecretStr("..."),
    )

The SDK detects ``client_secret`` and switches to the client credentials flow automatically. ``env`` is not used in this mode.

Using another method
""""""""""""""""""""

A single POST against the token endpoint:

.. code-block:: bash

    curl -X POST https://auth.evidence-repository.org/realms/destiny/protocol/openid-connect/token \
        -d grant_type=client_credentials \
        -d client_id=$DESTINY_CLIENT_ID \
        -d client_secret=$DESTINY_CLIENT_SECRET \
        -d scope=openid

The response contains ``access_token``. Unlike the interactive flow there is no ``refresh_token`` — re-POST the same request when the token expires.


Using the token
---------------

The API base URL for each environment is as follows:

.. csv-table:: API URLs
    :header: "Environment", "API URL"

    "Development", "https://api.dev.evidence-repository.org"
    "Staging", "https://api.staging.evidence-repository.org"
    "Production", "https://api.evidence-repository.org"

Using the SDK
^^^^^^^^^^^^^

Again, we recommend using the :doc:`SDK <../sdk/client>` to make API requests, as it will handle including the token for you. Some endpoints will have convenience methods available, otherwise you can access the underlying ``httpx`` client directly.

.. autoclass:: destiny_sdk.client.OAuthClient
    :no-index:

Using directly
^^^^^^^^^^^^^^

When making API requests, include the token in the ``Authorization`` header following ``Bearer``, eg:

.. code-block:: bash

    curl https://api.evidence-repository.org/v1/references/search/?q=example \
        -H "Authorization: Bearer $ACCESS_TOKEN"

The tokens will expire after a certain period (usually two hours). After expiration, you will need to obtain a new token using the same method as before.


Troubleshooting
---------------

Please reach out if you experience any issues either obtaining or using tokens - most likely, we need to update some permissions.
