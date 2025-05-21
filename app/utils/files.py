"""Utilities for file handling."""

import httpx
from fastapi import status


def check_signed_url(
    url: str,
) -> str | None:
    """
    Check if a signed URL is valid by making a request to it.

    The file is not downloaded.

    :param url: The signed URL to check.
    :type url: str
    :return: None if the signed URL is valid, str error otherwise.
    :rtype: str | None
    """
    try:
        with httpx.Client() as client:
            response = client.get(url)
            if response.status_code == status.HTTP_200_OK:
                return None
            return response.text
    except httpx.RequestError as e:
        return str(e)
