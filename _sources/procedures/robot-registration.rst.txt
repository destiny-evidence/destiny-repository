Registering a Robot
===================

.. contents:: Table of Contents
    :depth: 2
    :local:

.. mermaid::

    sequenceDiagram
        Actor RO as Robot Owner
        participant DR as Data Repository

        RO->>+DR: POST /robot/ : (base_url, description, name, owner)
        DR-->>DR: Register Robot
        DR->>RO: Provisioned Robot : (id, client_secret, parameters)
        Note over RO: Robot Owner configures robot with <br>provided id and client_secret

        RO->>+DR: PUT /robot/ : (id, new_base_url, new_description, new_name, new_owner)
        DR-->>DR: Update Robot
        DR->>RO: Robot(id, new_base_url, new_description, new_name, new_owner)
        Note over RO: client_secret not returned on update


        RO->>DR: Cycle Robot Secret (id)
        DR-->>DR: Cycle Robot Secret
        DR->>RO: Provisioned Robot (robot_id, base_url, new_client_secret, description, name, owner)
        Note over RO: Robot Owner updates robot with <br>new client_secret

For Robot Owners
----------------
The robot owner calls the ``POST /robot/`` endpoint with a :class:`RobotIn <libs.sdk.src.destiny_sdk.robots.RobotIn>` object, providing details of the robot.

Once confirmed by the repository, the robot owner will receive a :class:`ProvisionedRobot <libs.sdk.src.destiny_sdk.robots.ProvisionedRobot>` object containing the robot id, a client_secret, and the details provided in the original request.

Robot registration can also be performed with the destiny repository cli, see :ref:`robot-registration-cli`.

The robot owner can cycle the robot client_secret by calling ``POST /robot/<robot_id>/secret/``.

Once confirmed by the repository the robot owner with receive a :class:`ProvisionedRobot <libs.sdk.src.destiny_sdk.robots.ProvisionedRobot>` object containing the robot id, a new client_secret, and the robot details.

The client_secret is provided in response body *only* during registration, or when cycled with the ``POST /robot/<robot_id>/secret/`` endpoint.

The robot owner can update the robot details by calling ``PUT /robot/`` with a :class:`Robot <libs.sdk.src.destiny_sdk.robots.Robot>`, providing the robot id and robot details.

Once confirmed by the repository, the robot owner will receive a :class:`Robot <libs.sdk.src.destiny_sdk.robots.Robot>` object containing the robot id and robot details.

The robot owner can check the robot details by calling the ``GET /robot/<robot_id>`` endpoint, and will receive a :class:`Robot <libs.sdk.src.destiny_sdk.robots.Robot>` object containing the robot id and robot details.

For Robots
----------
Robots must be configured witht the robot_id and client_secret provided by destiny repository, and use these with the Client in :class:`Client <libs.sdk.src.destiny_sdk.client.Client>` to authenticate against the destiny repository.
