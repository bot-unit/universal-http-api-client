# universal-http-api-client

Lightweight wrappers and adapters for building HTTP API clients in Python, optimized for internal services that use `httpx` and `pydantic`.

## Current State

This repository is intended to be copied into internal projects as source files.

Current file set:

- `__init__.py`
- `adapters.py`
- `wrapper.py`
- `async_wrapper.py`
- `response_utils.py`

There is no packaging metadata on purpose. The expected usage model is:

1. Copy the folder into your service codebase.
2. Import the wrappers/adapters locally.
3. Build a project-specific API client on top.

## What It Provides

- `SyncClientWrapper` for synchronous API clients
- `AsyncWrapper` for asynchronous API clients
- first-class support for `httpx`
- optional fallback adapters for `requests`, `aiohttp`, and `urllib3`
- unified `HttpResponse`, `HttpError`, `NetworkError`, and `TimeoutError`
- optional retries, default headers, base URL handling, and context-manager support
- response parsing through Pydantic models

## How To Embed

Recommended structure inside a service:

```text
your_service/
  clients/
    universal_http/
      adapters.py
      wrapper.py
      async_wrapper.py
      response_utils.py
      __init__.py
    billing_api.py
```

Then build your domain client on top of these files instead of importing the wrappers directly across the whole codebase.

## Preferred Path

If your service uses `httpx` and `pydantic`, the intended default path is:

- subclass `SyncClientWrapper` or `AsyncWrapper`
- do not pass a custom adapter unless you actually need one
- if you want explicit construction, use `create_httpx_sync_adapter()` or `create_httpx_async_adapter()`
- if you copy the folder as a package, import through `__init__.py`

That keeps integration small and predictable.

## Quick Example

### Async client

```python
from typing import List
from pydantic import BaseModel

from universal_http import AsyncWrapper


class User(BaseModel):
    id: int
    name: str
    email: str


class UsersApi(AsyncWrapper):
    async def get_user(self, user_id: int) -> User:
        return await self._request(
            "GET",
            f"/users/{user_id}",
            response_model=User,
        )

    async def list_users(self) -> List[User]:
        return await self._request(
            "GET",
            "/users",
            response_model=List[User],
        )
```

```python
async with UsersApi(base_url="https://api.example.com", timeout=10.0) as client:
    user = await client.get_user(1)
```

### Sync client

```python
from universal_http import SyncClientWrapper


class UsersApiSync(SyncClientWrapper):
    def get_user(self, user_id: int) -> User:
        return self._request(
            "GET",
            f"/users/{user_id}",
            response_model=User,
        )
```

```python
with UsersApiSync(base_url="https://api.example.com") as client:
    user = client.get_user(1)
```

## Configuration

Both wrappers accept:

- `base_url`: API base URL
- `http_client`: custom adapter instance
- `timeout`: default timeout in seconds
- `max_retries`: retry count
- `headers`: default request headers
- `verify`: TLS certificate verification flag
- `**adapter_kwargs`: backend-specific options

Useful adapter kwargs currently supported by the built-in adapters include:

- `backoff_factor`
- `retry_statuses`
- `retry_exceptions`
- `on_request`
- `on_response`

For `httpx`, the easiest explicit setup is:

```python
from universal_http import AsyncWrapper, create_httpx_async_adapter


class MyApi(AsyncWrapper):
    pass


client = MyApi(
    base_url="https://api.example.com",
    http_client=create_httpx_async_adapter(
        base_url="https://api.example.com",
        timeout=10.0,
        headers={"Authorization": "Bearer token"},
    ),
)
```

## `_request()` Behavior

`_request()` sends the request through the configured adapter and:

- returns `HttpResponse` when `response_model` is omitted
- parses JSON into a Pydantic model when `response_model=MyModel`
- parses JSON arrays into a list of Pydantic models when `response_model=List[MyModel]`
- raises `HttpError` for HTTP failures and validation/parsing failures

## Operational Notes

- The wrappers are intended to be subclassed once per external API.
- The default design target is `httpx + pydantic`.
- For critical systems, prefer direct wrapper usage or explicit `create_httpx_*_adapter()` helpers over the generic factory helper.
- `AsyncClientWrapper` is available as an alias for `AsyncWrapper` if you want symmetric naming with `SyncClientWrapper`.
- Pydantic v2 is assumed because response parsing uses `model_validate()`.
- If you copy these files into another project, keep them together because the wrappers depend on `adapters.py` and `response_utils.py`.

## Known Limitations

- No test suite yet
- Sync and async wrappers still duplicate some lifecycle/configuration logic
- Error mapping is intentionally simple and not yet normalized equally across all backends
- Non-`httpx` adapters are supported, but `httpx` is the only path that should be treated as the primary integration target
- This is intentionally not packaged as an installable library

## Recommended Next Steps

1. Add unit tests for adapters, retry logic, response parsing, and error mapping.
2. Keep hardening the `httpx` path first and treat the other adapters as optional compatibility layers.
3. Add one or two ready-made examples for auth, pagination, and service-specific error translation.
4. Decide which adapters are truly needed internally and remove dead backends if they are not used.
5. Add a tiny integration checklist for teams that copy these files into a new service.
