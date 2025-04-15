"""Shared types for the application."""

# https://github.com/python/typing/issues/182#issuecomment-1320974824
type JSON = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None
