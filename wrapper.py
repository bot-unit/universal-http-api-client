# -*- coding: UTF-8 -*-
"""
    This module defines the synchronous web API client.
"""
from typing import Optional, Dict, Any, Type, TypeVar, List as ListType
from pydantic import BaseModel

try:
    from .adapters import (
        SyncHttpClient,
        HttpxSyncAdapter,
    )
    from .response_utils import parse_response_model, ParsedResponse
except ImportError:
    from adapters import (  # type: ignore
        SyncHttpClient,
        HttpxSyncAdapter,
    )
    from response_utils import parse_response_model, ParsedResponse  # type: ignore

T = TypeVar('T', bound=BaseModel)

class SyncClientWrapper:
    """
    The main synchronous client for an API.
    """
    def __init__(
        self,
        base_url: str,
        http_client: Optional[SyncHttpClient] = None,
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
            self.http_client = HttpxSyncAdapter(**adapter_config)
            self._owns_client = True
        else:
            if getattr(http_client, "is_async", False):
                raise TypeError("SyncClientWrapper requires a synchronous http_client.")
            self.http_client = http_client
            self._owns_client = False

        self.base_url = base_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the underlying HTTP client and release resources."""
        if self._owns_client and hasattr(self.http_client, 'close'):
            self.http_client.close()

    def _request(
        self,
        method: str,
        path: str,
        response_model: Optional[Type[T] | Type[ListType[T]]] = None,
        **kwargs: Any
    ) -> ParsedResponse:
        """
        Internal helper to make sync HTTP requests and parse responses.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API endpoint path (will be joined with base_url by adapter)
            response_model: Pydantic model to parse response into
            **kwargs: Additional request parameters (params, json, headers, etc.)

        Returns:
            Parsed Pydantic model, list of models, or raw HttpResponse

        Raises:
            HttpError: For HTTP errors (4xx, 5xx)
            NetworkError: For connection errors
            TimeoutError: For request timeouts
        """
        response = self.http_client.request(method, path, **kwargs)
        return parse_response_model(response, path, response_model)
