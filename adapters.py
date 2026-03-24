# -*- coding: UTF-8 -*-
"""
    This module defines the HTTP client interface and its implementations.
"""

from typing import Protocol, Any, Dict, Optional, Union, Callable
import time
import random
import json as _json
import asyncio

# --- Unified response and errors ---

class HttpResponse:
    def __init__(self, status_code: int, headers: Dict[str, str], content: bytes):
        self.status_code = status_code
        self.headers = headers
        self._content = content or b""

    def json(self) -> Any:
        if not self._content:
            raise ValueError(f"Cannot parse JSON from empty response body. Status code: {self.status_code}")
        try:
            return _json.loads(self._content.decode('utf-8'))
        except Exception as e:
            raise ValueError(f"Response is not valid JSON: {e}")

    def text(self, encoding: Optional[str] = None) -> str:
        enc = encoding or 'utf-8'
        try:
            return self._content.decode(enc)
        except Exception:
            # best-effort fallback
            return self._content.decode('utf-8', errors='replace')

    @property
    def content(self) -> bytes:
        return self._content

class HttpError(Exception):
    def __init__(self, status_code: Optional[int], message: str, body: Optional[bytes] = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or b""

class NetworkError(Exception):
    pass

class TimeoutError(Exception):
    pass

# Using Protocols for structural typing

class SyncHttpClient(Protocol):
    is_async: bool
    def request(self, method: str, url: str, *, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, data: Optional[Union[Dict[str, Any], bytes, str]] = None, timeout: Optional[float] = None, **kwargs: Any) -> HttpResponse: ...
    def close(self) -> None: ...

class AsyncHttpClient(Protocol):
    is_async: bool
    async def request(self, method: str, url: str, *, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, data: Optional[Union[Dict[str, Any], bytes, str]] = None, timeout: Optional[float] = None, **kwargs: Any) -> HttpResponse: ...
    async def aclose(self) -> None: ...

# --- Utilities ---

def _merge_headers(defaults: Optional[Dict[str, str]], headers: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    if defaults and headers:
        merged = defaults.copy()
        merged.update(headers)
        return merged
    return headers or defaults

def _join_base_url(base_url: Optional[str], url: str) -> str:
    if not base_url:
        return url

    # Remove trailing slash from base_url if present
    base = base_url.rstrip('/')

    # Ensure url starts with /
    path = url if url.startswith('/') else '/' + url

    # Simple concatenation: base + path
    # Example: https://127.0.0.1:5000/v1/api + /auth/status
    # Result: https://127.0.0.1:5000/v1/api/auth/status
    return base + path

# Add simple retry helpers
def _should_retry(status: Optional[int], exc: Optional[BaseException], retry_statuses: Optional[tuple] = None, retry_exceptions: Optional[tuple] = None) -> bool:
    if exc is not None:
        if retry_exceptions and isinstance(exc, retry_exceptions):
            return True
        # If no explicit exceptions configured, treat any exception as retryable
        return retry_exceptions is None
    if status is None:
        return False
    return retry_statuses is not None and status in retry_statuses

def _sleep_backoff(attempt: int, backoff_factor: float) -> None:
    # exponential backoff with jitter
    base = backoff_factor * (2 ** max(0, attempt - 1))
    jitter = base * 0.1 * random.random()
    time.sleep(base + jitter)

async def _async_sleep_backoff(attempt: int, backoff_factor: float) -> None:
    # exponential backoff with jitter without blocking the event loop
    base = backoff_factor * (2 ** max(0, attempt - 1))
    jitter = base * 0.1 * random.random()
    await asyncio.sleep(base + jitter)

# --- Concrete Implementations ---

class RequestsAdapter:
    """Synchronous adapter for the 'requests' library."""
    def __init__(self, **client_kwargs: Any):
        import importlib
        try:
            requests = importlib.import_module('requests')
        except ImportError as e:
            raise ImportError("RequestsAdapter requires 'requests' to be installed. Install with: pip install requests") from e
        self.session = requests.Session()
        self._base_url = client_kwargs.pop('base_url', None)
        self._default_timeout = client_kwargs.pop('timeout', None)
        self._max_retries = int(client_kwargs.pop('max_retries', 0) or 0)
        self._backoff_factor = float(client_kwargs.pop('backoff_factor', 0.0) or 0.0)
        self._retry_statuses = tuple(client_kwargs.pop('retry_statuses', (429, 503)))
        try:
            requests_errors = importlib.import_module('requests').exceptions
            default_retry_exceptions = (requests_errors.ConnectionError, requests_errors.Timeout)
            self._timeout_exc = requests_errors.Timeout
            self._conn_exc = requests_errors.ConnectionError
        except Exception:
            default_retry_exceptions = ()
            class _T(Exception): pass
            self._timeout_exc = _T
            self._conn_exc = _T
        self._retry_exceptions = tuple(client_kwargs.pop('retry_exceptions', default_retry_exceptions))
        # Hooks
        self._on_request: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_request', None)
        self._on_response: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_response', None)
        # Client-level kwargs
        default_headers = client_kwargs.pop('headers', None)
        if default_headers:
            self.session.headers.update(default_headers)
        for key in ('verify', 'proxies', 'auth', 'cookies'):
            if key in client_kwargs:
                setattr(self.session, key, client_kwargs.pop(key))
        self._default_request_kwargs = client_kwargs

    @property
    def is_async(self) -> bool:
        return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        self.session.close()

    def request(self, method: str, url: str, *, params=None, json=None, headers=None, data=None, timeout=None, **kwargs) -> HttpResponse:
        req_kwargs = {**self._default_request_kwargs, **kwargs}
        merged_headers = _merge_headers(self.session.headers if hasattr(self.session, 'headers') else None, headers)
        final_url = _join_base_url(self._base_url, url)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                if self._on_request:
                    self._on_request({"method": method, "url": final_url, "headers": merged_headers or {}, "params": params})
                response = self.session.request(
                    method,
                    final_url,
                    params=params,
                    json=json,
                    headers=merged_headers,
                    data=data,
                    timeout=effective_timeout,
                    **req_kwargs,
                )
                status = response.status_code
                if _should_retry(status, None, self._retry_statuses, self._retry_exceptions) and attempt <= self._max_retries:
                    _sleep_backoff(attempt, self._backoff_factor)
                    continue
                # Build normalized response
                resp = HttpResponse(status_code=response.status_code, headers=dict(response.headers or {}), content=response.content)
                if 400 <= response.status_code:
                    raise HttpError(response.status_code, f"HTTP error {response.status_code}", resp.content)
                if self._on_response:
                    self._on_response({"method": method, "url": final_url, "status": resp.status_code, "headers": resp.headers})
                return resp
            except Exception as e:
                if isinstance(e, HttpError):
                    raise
                # Map exceptions
                if isinstance(e, self._timeout_exc):
                    raise TimeoutError(str(e)) from e
                if isinstance(e, self._conn_exc):
                    if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                        _sleep_backoff(attempt, self._backoff_factor)
                        continue
                    raise NetworkError(str(e)) from e
                if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                    _sleep_backoff(attempt, self._backoff_factor)
                    continue
                raise HttpError(None, f"Request failed: {e}") from e
        # Should never reach here
        raise HttpError(None, "Unexpected state in RequestsAdapter.request")

class HttpxSyncAdapter:
    """Synchronous adapter for the 'httpx' library."""
    def __init__(self, **client_kwargs: Any):
        import importlib
        try:
            httpx = importlib.import_module('httpx')
        except ImportError as e:
            raise ImportError("HttpxSyncAdapter requires 'httpx' to be installed. Install with: pip install httpx") from e

        # Extract our custom parameters that httpx doesn't understand
        self._base_url = client_kwargs.pop('base_url', None)
        self._default_timeout = client_kwargs.pop('timeout', None)
        self._max_retries = int(client_kwargs.pop('max_retries', 0) or 0)
        self._backoff_factor = float(client_kwargs.pop('backoff_factor', 0.0) or 0.0)
        self._retry_statuses = tuple(client_kwargs.pop('retry_statuses', (429, 503)))
        self._retry_exceptions = tuple(client_kwargs.pop('retry_exceptions', ()))
        self._on_request: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_request', None)
        self._on_response: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_response', None)

        # Set up exception types
        try:
            httpx_mod = importlib.import_module('httpx')
            if not self._retry_exceptions:
                self._retry_exceptions = (httpx_mod.ConnectError, httpx_mod.ReadTimeout)
            self._timeout_exc = httpx_mod.ReadTimeout
            self._conn_exc = httpx_mod.ConnectError
        except Exception:
            class _T(Exception): pass
            self._timeout_exc = _T
            self._conn_exc = _T

        # Now pass remaining kwargs to httpx.Client (base_url and timeout if present)
        httpx_kwargs = {
            'follow_redirects': True,  # Follow redirects by default (e.g., 302, 301)
        }
        if self._base_url:
            httpx_kwargs['base_url'] = self._base_url
        if self._default_timeout is not None:
            httpx_kwargs['timeout'] = self._default_timeout
        httpx_kwargs.update(client_kwargs)  # Add any other httpx-compatible kwargs (can override follow_redirects)

        self.client = httpx.Client(**httpx_kwargs)

    @property
    def is_async(self) -> bool:
        return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, url: str, *, params=None, json=None, headers=None, data=None, timeout=None, **kwargs) -> HttpResponse:
        final_url = _join_base_url(self._base_url, url)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                if self._on_request:
                    self._on_request({"method": method, "url": final_url, "headers": headers or {}, "params": params})
                response = self.client.request(
                    method,
                    final_url,
                    params=params,
                    json=json,
                    headers=headers,
                    data=data,
                    timeout=effective_timeout,
                    **kwargs,
                )
                status = response.status_code
                if _should_retry(status, None, self._retry_statuses, self._retry_exceptions) and attempt <= self._max_retries:
                    _sleep_backoff(attempt, self._backoff_factor)
                    continue
                resp = HttpResponse(status_code=response.status_code, headers=dict(response.headers or {}), content=response.content)
                if 400 <= response.status_code:
                    raise HttpError(response.status_code, f"HTTP error {response.status_code}", resp.content)
                if self._on_response:
                    self._on_response({"method": method, "url": final_url, "status": resp.status_code, "headers": resp.headers})
                return resp
            except Exception as e:
                if isinstance(e, HttpError):
                    raise
                if isinstance(e, self._timeout_exc):
                    raise TimeoutError(str(e)) from e
                if isinstance(e, self._conn_exc):
                    if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                        _sleep_backoff(attempt, self._backoff_factor)
                        continue
                    raise NetworkError(str(e)) from e
                if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                    _sleep_backoff(attempt, self._backoff_factor)
                    continue
                raise HttpError(None, f"Request failed: {e}") from e
        raise HttpError(None, "Unexpected state in HttpxSyncAdapter.request")

class HttpxAsyncAdapter:
    """Asynchronous adapter for the 'httpx' library."""
    def __init__(self, **client_kwargs: Any):
        import importlib
        try:
            httpx = importlib.import_module('httpx')
        except ImportError as e:
            raise ImportError("HttpxAsyncAdapter requires 'httpx' to be installed. Install with: pip install httpx") from e

        # Extract our custom parameters that httpx doesn't understand
        self._base_url = client_kwargs.pop('base_url', None)
        self._default_timeout = client_kwargs.pop('timeout', None)
        self._max_retries = int(client_kwargs.pop('max_retries', 0) or 0)
        self._backoff_factor = float(client_kwargs.pop('backoff_factor', 0.0) or 0.0)
        self._retry_statuses = tuple(client_kwargs.pop('retry_statuses', (429, 503)))
        self._retry_exceptions = tuple(client_kwargs.pop('retry_exceptions', ()))
        self._on_request: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_request', None)
        self._on_response: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_response', None)

        # Set up exception types
        try:
            httpx_mod = importlib.import_module('httpx')
            if not self._retry_exceptions:
                self._retry_exceptions = (httpx_mod.ConnectError, httpx_mod.ReadTimeout)
            self._timeout_exc = httpx_mod.ReadTimeout
            self._conn_exc = httpx_mod.ConnectError
        except Exception:
            class _T(Exception): pass
            self._timeout_exc = _T
            self._conn_exc = _T

        # Now pass remaining kwargs to httpx.AsyncClient (base_url and timeout if present)
        httpx_kwargs = {
            'follow_redirects': True,  # Follow redirects by default (e.g., 302, 301)
        }
        if self._base_url:
            httpx_kwargs['base_url'] = self._base_url
        if self._default_timeout is not None:
            httpx_kwargs['timeout'] = self._default_timeout
        httpx_kwargs.update(client_kwargs)  # Add any other httpx-compatible kwargs (can override follow_redirects)

        self.client = httpx.AsyncClient(**httpx_kwargs)

    @property
    def is_async(self) -> bool:
        return True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    async def request(self, method: str, url: str, *, params=None, json=None, headers=None, data=None, timeout=None, **kwargs) -> HttpResponse:
        final_url = _join_base_url(self._base_url, url)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                if self._on_request:
                    self._on_request({"method": method, "url": final_url, "headers": headers or {}, "params": params})
                response = await self.client.request(
                    method,
                    final_url,
                    params=params,
                    json=json,
                    headers=headers,
                    data=data,
                    timeout=effective_timeout,
                    **kwargs,
                )
                status = response.status_code
                if _should_retry(status, None, self._retry_statuses, self._retry_exceptions) and attempt <= self._max_retries:
                    await _async_sleep_backoff(attempt, self._backoff_factor)
                    continue
                resp = HttpResponse(status_code=response.status_code, headers=dict(response.headers or {}), content=response.content)
                if 400 <= response.status_code:
                    raise HttpError(response.status_code, f"HTTP error {response.status_code}", resp.content)
                if self._on_response:
                    self._on_response({"method": method, "url": final_url, "status": resp.status_code, "headers": resp.headers})
                return resp
            except Exception as e:
                if isinstance(e, HttpError):
                    raise
                if isinstance(e, self._timeout_exc):
                    raise TimeoutError(str(e)) from e
                if isinstance(e, self._conn_exc):
                    if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                        await _async_sleep_backoff(attempt, self._backoff_factor)
                        continue
                    raise NetworkError(str(e)) from e
                if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                    await _async_sleep_backoff(attempt, self._backoff_factor)
                    continue
                raise HttpError(None, f"Request failed: {e}") from e
        raise HttpError(None, "Unexpected state in HttpxAsyncAdapter.request")

class AiohttpAdapter:
    """Asynchronous adapter for the 'aiohttp' library."""
    def __init__(self, **client_kwargs: Any):
        import importlib
        try:
            aiohttp = importlib.import_module('aiohttp')
        except ImportError as e:
            raise ImportError("AiohttpAdapter requires 'aiohttp' to be installed. Install with: pip install aiohttp") from e
        self._base_url = client_kwargs.pop('base_url', None)
        self._default_timeout = client_kwargs.pop('timeout', None)
        self._max_retries = int(client_kwargs.pop('max_retries', 0) or 0)
        self._backoff_factor = float(client_kwargs.pop('backoff_factor', 0.0) or 0.0)
        self._retry_statuses = tuple(client_kwargs.pop('retry_statuses', (429, 503)))
        try:
            aiohttp_mod = importlib.import_module('aiohttp')
            default_retry_exceptions = (aiohttp_mod.ClientConnectorError, aiohttp_mod.ServerTimeoutError)
            self._timeout_exc = aiohttp_mod.ServerTimeoutError
            self._conn_exc = aiohttp_mod.ClientConnectorError
        except Exception:
            default_retry_exceptions = ()
            class _T(Exception): pass
            self._timeout_exc = _T
            self._conn_exc = _T
        self._retry_exceptions = tuple(client_kwargs.pop('retry_exceptions', default_retry_exceptions))
        self._on_request: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_request', None)
        self._on_response: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_response', None)
        self.session = aiohttp.ClientSession(**client_kwargs)

    @property
    def is_async(self) -> bool:
        return True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    async def aclose(self) -> None:
        await self.session.close()

    async def request(self, method: str, url: str, *, params=None, json=None, headers=None, data=None, timeout=None, **kwargs) -> HttpResponse:
        final_url = _join_base_url(self._base_url, url)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                if self._on_request:
                    self._on_request({"method": method, "url": final_url, "headers": headers or {}, "params": params})
                async with self.session.request(
                    method,
                    final_url,
                    params=params,
                    json=json,
                    headers=headers,
                    data=data,
                    timeout=effective_timeout,
                    **kwargs,
                ) as response:
                    status = response.status
                    if _should_retry(status, None, self._retry_statuses, self._retry_exceptions) and attempt <= self._max_retries:
                        await _async_sleep_backoff(attempt, self._backoff_factor)
                        continue
                    content = await response.read()
                    resp = HttpResponse(status_code=response.status, headers=dict(response.headers or {}), content=content)
                    if 400 <= response.status:
                        raise HttpError(response.status, f"HTTP error {response.status}", resp.content)
                    if self._on_response:
                        self._on_response({"method": method, "url": final_url, "status": resp.status_code, "headers": resp.headers})
                    return resp
            except Exception as e:
                if isinstance(e, HttpError):
                    raise
                if isinstance(e, self._timeout_exc):
                    raise TimeoutError(str(e)) from e
                if isinstance(e, self._conn_exc):
                    if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                        await _async_sleep_backoff(attempt, self._backoff_factor)
                        continue
                    raise NetworkError(str(e)) from e
                if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                    await _async_sleep_backoff(attempt, self._backoff_factor)
                    continue
                raise HttpError(None, f"Request failed: {e}") from e
        raise HttpError(None, "Unexpected state in AiohttpAdapter.request")

class Urllib3Adapter:
    """Synchronous adapter for the 'urllib3' library using PoolManager."""
    def __init__(self, **client_kwargs: Any):
        import importlib
        try:
            urllib3 = importlib.import_module('urllib3')
        except ImportError as e:
            raise ImportError("Urllib3Adapter requires 'urllib3' to be installed. Install with: pip install urllib3") from e
        self._default_headers = client_kwargs.pop('headers', None)
        self._base_url = client_kwargs.pop('base_url', None)
        self._default_timeout = client_kwargs.pop('timeout', None)
        self._max_retries = int(client_kwargs.pop('max_retries', 0) or 0)
        self._backoff_factor = float(client_kwargs.pop('backoff_factor', 0.0) or 0.0)
        self._retry_statuses = tuple(client_kwargs.pop('retry_statuses', (429, 503)))
        try:
            urllib3_exceptions = urllib3.exceptions
            default_retry_exceptions = (
                urllib3_exceptions.ConnectTimeoutError,
                urllib3_exceptions.ReadTimeoutError,
                urllib3_exceptions.NewConnectionError,
                urllib3_exceptions.MaxRetryError,
            )
            self._timeout_exc = (
                urllib3_exceptions.ConnectTimeoutError,
                urllib3_exceptions.ReadTimeoutError,
                urllib3_exceptions.TimeoutError,
            )
            self._conn_exc = (
                urllib3_exceptions.NewConnectionError,
                urllib3_exceptions.MaxRetryError,
            )
        except Exception:
            default_retry_exceptions = ()
            self._timeout_exc = ()
            self._conn_exc = ()
        self._retry_exceptions = tuple(client_kwargs.pop('retry_exceptions', default_retry_exceptions))
        self._on_request: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_request', None)
        self._on_response: Optional[Callable[[Dict[str, Any]], None]] = client_kwargs.pop('on_response', None)
        self.http = urllib3.PoolManager(**client_kwargs)

    @property
    def is_async(self) -> bool:
        return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        try:
            self.http.clear()
        except Exception:
            pass

    def request(self, method: str, url: str, *, params=None, json=None, headers=None, data=None, timeout=None, **kwargs) -> HttpResponse:
        url = _join_base_url(self._base_url, url)
        if params:
            from urllib.parse import urlencode, urlsplit, urlunsplit
            scheme, netloc, path, query, fragment = urlsplit(url)
            q = urlencode(params, doseq=True)
            query = f"{query}&{q}" if query else q
            url = urlunsplit((scheme, netloc, path, query, fragment))
        body = data
        if json is not None:
            body = _json.dumps(json).encode('utf-8')
            headers = headers or {}
            headers = {**headers, 'Content-Type': 'application/json'}
        merged_headers = _merge_headers(self._default_headers, headers)
        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout is not None:
            kwargs['timeout'] = effective_timeout
        attempt = 0
        while True:
            attempt += 1
            try:
                if self._on_request:
                    self._on_request({"method": method, "url": url, "headers": merged_headers or {}, "params": params})
                r = self.http.request(method.upper(), url, body=body, headers=merged_headers, **kwargs)
                status = getattr(r, 'status', None)
                if _should_retry(status, None, self._retry_statuses, self._retry_exceptions) and attempt <= self._max_retries:
                    _sleep_backoff(attempt, self._backoff_factor)
                    continue
                content = r.data
                resp = HttpResponse(status_code=status or 0, headers=dict(r.headers or {}), content=content)
                if status and 400 <= status:
                    raise HttpError(status, f"HTTP error {status}", resp.content)
                if self._on_response:
                    self._on_response({"method": method, "url": url, "status": resp.status_code, "headers": resp.headers})
                return resp
            except Exception as e:
                if isinstance(e, HttpError):
                    raise
                if attempt <= self._max_retries and _should_retry(None, e, self._retry_statuses, self._retry_exceptions):
                    _sleep_backoff(attempt, self._backoff_factor)
                    continue
                if self._timeout_exc and isinstance(e, self._timeout_exc):
                    raise TimeoutError(str(e)) from e
                if self._conn_exc and isinstance(e, self._conn_exc):
                    raise NetworkError(str(e)) from e
                raise HttpError(None, f"Request failed: {e}") from e
        raise HttpError(None, "Unexpected state in Urllib3Adapter.request")

# --- Factory ---

def create_httpx_sync_adapter(**client_kwargs: Any) -> SyncHttpClient:
    """Preferred sync adapter factory for internal services using httpx."""
    return HttpxSyncAdapter(**client_kwargs)


def create_httpx_async_adapter(**client_kwargs: Any) -> AsyncHttpClient:
    """Preferred async adapter factory for internal services using httpx."""
    return HttpxAsyncAdapter(**client_kwargs)


def create_adapter(
    backend: str = "httpx-sync",
    *,
    is_async: Optional[bool] = None,
    **client_kwargs: Any,
) -> Union[SyncHttpClient, AsyncHttpClient]:
    """Create an adapter by backend name.

    Preferred internal defaults are httpx-based and explicit:
    - `httpx-sync`
    - `httpx-async`

    For backward compatibility:
    - `httpx` + `is_async=True` -> async adapter
    - `httpx` + `is_async=False/None` -> sync adapter
    """
    name = (backend or "httpx-sync").lower()
    if name == "httpx-sync" or name == "httpx_sync":
        return HttpxSyncAdapter(**client_kwargs)  # type: ignore[return-value]
    if name == "httpx-async" or name == "httpx_async":
        return HttpxAsyncAdapter(**client_kwargs)  # type: ignore[return-value]
    if name == "httpx":
        if is_async:
            return HttpxAsyncAdapter(**client_kwargs)  # type: ignore[return-value]
        return HttpxSyncAdapter(**client_kwargs)  # type: ignore[return-value]
    if name == "requests":
        return RequestsAdapter(**client_kwargs)  # type: ignore[return-value]
    if name == "aiohttp":
        return AiohttpAdapter(**client_kwargs)  # type: ignore[return-value]
    if name == "urllib3":
        return Urllib3Adapter(**client_kwargs)  # type: ignore[return-value]
    raise ValueError(
        f"Unsupported backend '{backend}'. "
        "Use one of: httpx, httpx-sync, httpx-async, requests, aiohttp, urllib3."
    )
