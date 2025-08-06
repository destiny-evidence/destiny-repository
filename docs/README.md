# Sphinx Documentation

This is a simple sphinx implementation to add model and procedure documentation.

It is hosted on Github [here](https://destiny-evidence.github.io/destiny-repository/).

Over time we will expand this to include formal function documentation.

## Local

To build the docs run the following from the project root directory:

```sh
uv sync --group docs
uv run --directory docs/ sphinx-build -b html . html
```

Note: [graphviz](https://www.graphviz.org) is a requirement on the building machine. On my mac I had to do the below before `uv sync --group docs`:

```sh
brew install graphviz
export CFLAGS="-I $(brew --prefix graphviz)/include"
export LDFLAGS="-L $(brew --prefix graphviz)/lib"
```

To view the docs:

```sh
open docs/html/index.html
```
