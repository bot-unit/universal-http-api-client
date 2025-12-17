# -*- coding: UTF-8 -*-
"""
    This module defines the asynchronous web API client.
"""

from typing import Optional, Dict, Any, Type, TypeVar
from typing import List as ListType
from pydantic import BaseModel

from src.client.adapters import (
    AsyncHttpClient,
    HttpxAsyncAdapter,
    HttpResponse,
    HttpError,
)

T = TypeVar('T', bound=BaseModel)

class AsyncWrapper:
    """
    The main asynchronous client for API.
    """
    def __init__(
        self,
        base_url: str,
        http_client: Optional[AsyncHttpClient] = None,
        timeout: Optional[float] = None,
        max_retries: int = 0,
        headers: Optional[Dict[str, str]] = None,
        verify: bool = True,
        **adapter_kwargs: Any
    ):
        if http_client is None:
            # Build adapter config from provided params
            adapter_config: Dict[str, Any] = {
                'base_url': base_url,
                'timeout': timeout,
                'max_retries': max_retries,
                'verify': verify,
            }
            if headers:
                adapter_config['headers'] = headers
            adapter_config.update(adapter_kwargs)
            self.http_client = HttpxAsyncAdapter(**adapter_config)
            self._owns_client = True
        else:
            self.http_client = http_client
            self._owns_client = False

        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """
        Close the underlying HTTP client session and release resources.
        Uses the protocol's aclose() method for proper cleanup.
        """
        if self._owns_client and hasattr(self.http_client, 'aclose'):
            await self.http_client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        response_model: Optional[Type[T] | Type[ListType[T]]] = None,
        **kwargs: Any
    ) -> T:
        """
        Internal helper to make async HTTP requests and parse responses.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path (will be joined with base_url by adapter)
            response_model: Pydantic model to parse response into
            **kwargs: Additional request parameters (params, json, headers, etc.)

        Returns:
            Parsed Pydantic model instance if response_model provided, else raw response

        Raises:
            HttpError: For HTTP errors (4xx, 5xx)
            NetworkError: For connection errors
            TimeoutError: For request timeouts
        """
        response: HttpResponse = await self.http_client.request(method, path, **kwargs)

        if response_model is None:
            return response  # type: ignore

        # Parse JSON response into Pydantic model
        try:
            data = response.json()
        except ValueError as e:
            # response.json() failed - either empty body or invalid JSON
            status = response.status_code

            # Better error messages for common HTTP errors
            if status == 404:
                raise HttpError(
                    status,
                    f"Endpoint not found (404): {path}\n"
                    f"Check that the endpoint path is correct and the API is running.\n"
                    f"Error: {e}"
                ) from e
            elif status == 401 or status == 403:
                raise HttpError(
                    status,
                    f"Unauthorized ({status}): {path}\n"
                    f"Check authentication/authorization.\n"
                    f"Error: {e}"
                ) from e
            elif status >= 500:
                raise HttpError(
                    status,
                    f"Server error ({status}): {path}\n"
                    f"The API server returned an error.\n"
                    f"Error: {e}"
                ) from e
            else:
                raise HttpError(
                    status,
                    f"Failed to parse JSON response from {path}: {e}\n"
                    f"Response status: {status}\n"
                    f"Response body: {response.content}"
                ) from e

        try:
            # Check if response_model is a list type (e.g., List[SomeModel])
            import typing
            origin = typing.get_origin(response_model)

            if origin is list:
                # Get the item type from List[ItemType]
                args = typing.get_args(response_model)
                if args and isinstance(data, list):
                    item_model = args[0]
                    # If item type is not a Pydantic model, return raw list
                    if not hasattr(item_model, 'model_validate'):
                        return data  # type: ignore
                    # Else, parse each item with Pydantic model
                    return [item_model.model_validate(item) for item in data]  # type: ignore

            # Regular Pydantic model
            return response_model.model_validate(data)
        except Exception as e:
            raise HttpError(
                response.status_code,
                f"Failed to validate response model for {path}: {e}\n"
                f"Expected model: {response_model.__name__ if hasattr(response_model, '__name__') else response_model}\n"
                f"Got data: {data}"
            ) from e
