"""Decorators for API endpoints."""

from fastapi.types import DecoratedCallable

EXPERIMENTAL_NOTE = """\
> ⚠️ **Experimental**
>
> This endpoint is experimental and may change without notice.


"""


def experimental(func: DecoratedCallable) -> DecoratedCallable:
    """
    Mark an API endpoint as experimental in its documentation.

    Mutates the handler's docstring, so it must be applied *below* the route
    decorator (it runs first, before registration) and only works for routes
    that derive their OpenAPI description from the docstring.
    """
    func.__doc__ = EXPERIMENTAL_NOTE + (func.__doc__ or "")
    return func
