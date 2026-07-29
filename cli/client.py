"""Shared CLI plumbing: an argument parser that yields a configured API client."""

import argparse
from collections.abc import Sequence
from typing import Literal, cast

import httpx
from destiny_sdk.client import OAuthClient

from app.core.config import Environment

LOCAL_REPOSITORY_URL = "http://127.0.0.1:8000"


def get_oauth_client(env: Environment, url: str | None = None) -> OAuthClient:
    """Build an authenticated ``OAuthClient`` for the given environment."""
    if env in Environment.local_envs():
        # No auth server locally; httpx.Auth is a no-op yielding unchanged.
        return OAuthClient(base_url=url or LOCAL_REPOSITORY_URL, auth=httpx.Auth())
    return OAuthClient(
        env=cast(Literal["development", "staging", "production"], env.value),
        base_url=url,
    )


def get_client(env: Environment, url: str | None = None) -> httpx.Client:
    """Build an authenticated httpx client for the given environment."""
    return get_oauth_client(env, url).get_client()


class ApiArgumentParser(argparse.ArgumentParser):
    """
    ArgumentParser that adds ``--env``/``--url`` and resolves them to a client.

    No network call is made until the client is first used, so ``--dry-run`` paths
    that never touch the client won't trigger authentication.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Add the shared ``--env`` and ``--url`` arguments."""
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.add_argument(
            "-e",
            "--env",
            type=Environment,
            default=Environment.LOCAL,
            help="Environment to target (default: local).",
        )
        self.add_argument(
            "--url",
            default=None,
            help=(
                f"Base URL override. Defaults to {LOCAL_REPOSITORY_URL} for "
                "local/test, and to the SDK's per-environment URL otherwise."
            ),
        )

    def parse_args(  # type: ignore[override]
        self,
        args: Sequence[str] | None = None,
        namespace: None = None,
    ) -> argparse.Namespace:
        """
        Parse arguments and attach configured clients to the namespace.

        Both ``oauth_client`` (the SDK :class:`OAuthClient`) and ``client`` (its
        underlying ``httpx.Client``) are attached; they share one session, so
        scripts can use whichever fits.
        """
        parsed = super().parse_args(args, namespace)
        parsed.oauth_client = get_oauth_client(parsed.env, parsed.url)
        parsed.client = parsed.oauth_client.get_client()
        return parsed
