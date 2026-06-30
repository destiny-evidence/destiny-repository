# Destiny Repository CLI

CLI for interacting with the destiny repository

Currently runs with the same set of installed dependencies as destiny repository.

## Configuration

Every command takes two shared options:

- `--env` (`-e`): one of `local`, `test`, `development`, `staging`, `production`. Defaults to `local`.
- `--url`: base URL override. Defaults to `http://127.0.0.1:8000` for `local`/`test`, and to the SDK's per-environment URL for `development`/`staging`/`production`.

The base URL and authentication for `development`, `staging`, and `production` are resolved by the SDK, so they need no further configuration. `local` and `test` skip authentication and target localhost (override with `--url`).

## Commands

Run everything from the destiny-repository root directory.

### Robot Registration

Use the following command to register a robot, passing the environment you wish to register the robot in.

You will need to be assigned the `robot.writer` role for destiny repository to be able to run this command.

```sh
uv run python -m cli.register_robot --name "NAME" --owner "OWNER" --description "DESCRIPTION" --env ENVIRONMENT
```
