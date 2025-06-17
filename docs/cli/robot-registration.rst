.. _robot-registration-cli:

Robot Registration
==================
Use the following command to register a robot, passing the environment you wish to register the robot in. This will load the required environment file.

You will need to be assigned the :code:`robot.writer` role for destiny repository to be able to run this command.

.. code:: bash

    poetry run python -m cli.register_robot --name "NAME" --owner "OWNER" --base-url "BASE_URL" --description "DESCRIPTION" --env ENVIRONMENT
