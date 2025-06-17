CLI Configuration
=================

Environment Files
-----------------

Set up `.env.<ENVIRONMENT>` files for each environment by copying the `.env.example` file in the `/cli` directory.

The CLI will then automatically select the correct environment file based on the `--env` flag set when running commands.

The CLI ignores any already set environment variables when executing, so the `.env` files must contain all variables for that environment.

Settings
--------

.. autopydantic_settings:: cli.config.Settings
