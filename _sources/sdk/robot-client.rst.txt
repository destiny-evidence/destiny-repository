SDK Robot Client
================

This documentation auto-generates details about the HMAC authentication and convenience methods provided by the SDK for robots.

.. contents::
    :depth: 2
    :local:

.. note::

    This document is about API authentication for robots. For anyone else, refer to :doc:`OAuth <../procedures/oauth>` and :doc:`SDK Client <client>`.

Client
------

.. autoclass:: libs.sdk.src.destiny_sdk.client.RobotClient
    :members:
    :undoc-members:
    :inherited-members:


HMAC Authentication
-------------------

The client will apply HMAC authentication automatically, but if you need to access the authentication itself you can access the below directly:

.. automodule:: libs.sdk.src.destiny_sdk.auth
    :members:
    :undoc-members:
    :inherited-members: BaseModel
