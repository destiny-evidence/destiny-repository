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
