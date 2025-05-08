# DESTINY SDK

SDK for interaction with the DESTINY repository

## Installing as an editable package for local sdk development

```sh
poetry add --editable ./PATH/TO/sdk/
```

or replace the dependency in `pyproject.toml` with

```toml
destiny-sdk = {path = "./PATH/TO/sdk/", develop = true}
```

## Installing elsewhere as a dependency

This will eventually live on PyPI - for now:

```sh
poetry add git+ssh://git@github.com:destiny-evidence/destiny-repository.git
```

or replace the dependency in `pyproject.toml` with

```toml
destiny-sdk = {git = "ssh://git@github.com:destiny-evidence/destiny-repository.git", subdirectory = "libs/sdk"}
```
