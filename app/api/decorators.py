"""Decorators for API endpoints."""

from fastapi.types import DecoratedCallable


def experimental(func: DecoratedCallable) -> DecoratedCallable:
    """Mark an API endpoint as experimental in its documentation."""
    _note = """
> ⚠️ **Experimental**
>
> This endpoint is experimental and may change without notice.


"""
    (
        "⚠️ **Experimental** <br/>"
        "This endpoint is experimental and may change without notice."
        "<br/><br/>"
    )

    # Update the docstring
    if func.__doc__:
        func.__doc__ = _note + func.__doc__
    else:
        func.__doc__ = _note

    return func
