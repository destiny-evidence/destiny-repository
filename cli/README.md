# Destiny Repository CLI

CLI for interacting with the destiny repository

Currently runs with the same set of installed dependencies as destiny repository.

## Configuration

set up `.env.<ENVIRONMENT>` files for each environment by copying the `.env.example` file in the `/cli` directory.

## Development

Environments`local` and `test` environment will skip authentication, expecting to hit a destiny repository deployed at `http://127.0.0.0:8000`.

You can override this by setting `DESTINY_REPOSITORY_URL` in the `.env.<ENVIRONMENT>` file.

Use dummy values for `AZURE_TENANT_ID`, `AZURE_APPLICATION_ID`, and `CLI_CLIENT_ID`

## Commands

Run everything from the destiny-repository root directory

### Robot Registration

Use the following command to register a robot, passing the environment you wish to register the robot in. This will load the required environment file.

You will need to be assigned the `robot.writer` role for destiny repository to be able to run this command.

```sh
poetry run python -m cli.register_robot --name "NAME" --owner "OWNER" --base-url "BASE_URL" --description "DESCRIPTION" --env ENVIRONMENT
```
