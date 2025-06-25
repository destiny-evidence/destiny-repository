# DESTINY SDK

SDK for interaction with the DESTINY repository. For now this just contains data models for validation and structuring, but will be built out to include convenience functions etc.

## Documentation

The documentation for destiny-sdk is hosted [here](https://destiny-evidence.github.io/destiny-repository/sdk/sdk.html)

## Installation from PyPI

```sh
pip install destiny-sdk
```

```sh
poetry add destiny-sdk
```

## Development

### Dependencies

```sh
poetry install
```

### Tests

```sh
poetry run pytest
```

### Installing as an editable package of another project

Run the following command in the root folder of the other project (assuming poetry as a packaging framework). Pip also has an `--editable` option that you can use.

```sh
poetry add --editable ./PATH/TO/sdk/
```

or replace the dependency in `pyproject.toml` with

```toml
destiny-sdk = {path = "./PATH/TO/sdk/", develop = true}
```

### Installing a local wheel

If you want to use a local build of the sdk `z.whl`, do

```sh
poetry build
poetry add ./PATH/TO/WHEEL.whl
```

### Publishing to test pypi

```sh
poetry config repositories.testpypi https://test.pypi.org/legacy/
poetry config pypi-token.testpypi [YOUR_TESTPYPI_TOKEN]
poetry publish --repository testpypi
```

## Publishing

```sh
poetry config pypi-token.pypi [YOUR_PYPI_TOKEN]
poetry publish
```

### Versioning

Follow the [semver](https://semver.org/) guidelines for versioning, tldr;

Given a version number `MAJOR.MINOR.PATCH`, increment the:

- `MAJOR` version when you make incompatible API change
- `MINOR` version when you add functionality in a backward compatible manner
- `PATCH` version when you make backward compatible bug fixes
