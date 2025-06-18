# DESTINY SDK

SDK for interaction with the DESTINY repository. For now this just contains data models for validation and structuring, but will be built out to include convenience functions etc.

## Installing as an editable package for local sdk development

```sh
poetry add --editable ./PATH/TO/sdk/
```

or replace the dependency in `pyproject.toml` with

```toml
destiny-sdk = {path = "./PATH/TO/sdk/", develop = true}
```

## Installing from PyPI

```sh
poetry add destiny-sdk
```

## Documentation

The documentation for destiny-sdk is hosted [here](https://destiny-evidence.github.io/destiny-repository/sdk/sdk.html)
