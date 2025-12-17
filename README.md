# universal-http-api-client

Python classes for building API clients with support for both synchronous and asynchronous HTTP operations.

## Overview

This library provides base wrapper classes for building HTTP API clients in Python. It abstracts HTTP client implementation details, provides automatic response parsing with Pydantic models, and offers a consistent API for making requests.

## Features

- **Base Wrapper Classes**: Ready-to-use `AsyncWrapper` and `SyncClientWrapper` for building API clients
- **Pydantic Integration**:  Automatic response parsing into Pydantic models
- **Protocol-based Adapters**: Uses Python's Protocol for structural typing, supporting both sync and async clients
- **Error Handling**: Built-in exception classes for HTTP errors, network errors, and timeouts
- **Context Manager Support**: Both sync and async context managers for automatic resource cleanup
- **Flexible Configuration**: Support for custom timeouts, retries, headers, and SSL verification
- **URL Management**:  Automatic base URL joining with endpoint paths

## Core Components

### Wrapper Classes

**`AsyncWrapper`** - Base class for asynchronous API clients:
- Automatic HTTP client initialization with `HttpxAsyncAdapter`
- Pydantic model response parsing
- Async context manager support
- Built-in error handling

**`SyncClientWrapper`** - Base class for synchronous API clients:
- Automatic HTTP client initialization with `HttpxSyncAdapter`
- Pydantic model response parsing
- Context manager support
- Built-in error handling

### Response & Error Handling

**`HttpResponse`** - Unified response object:
- `status_code`: HTTP status code
- `headers`: Response headers dictionary
- `content`: Raw bytes content
- `json()`: Parse response as JSON
- `text(encoding=None)`: Get response as text

**Exception Classes**:
- **`HttpError`**: HTTP-level errors (4xx, 5xx) with status code and response body
- **`NetworkError`**: Network-related issues
- **`TimeoutError`**: Request timeouts

### Adapters (Internal)

- **`HttpxAsyncAdapter`**: Async HTTP client adapter (httpx-based)
- **`HttpxSyncAdapter`**: Sync HTTP client adapter (httpx-based)
- Protocol interfaces:  `AsyncHttpClient`, `SyncHttpClient`

## Usage

### Creating Your API Client

Inherit from `AsyncWrapper` or `SyncClientWrapper` and implement your API methods:

```python
from async_wrapper import AsyncWrapper
from pydantic import BaseModel
from typing import List

class User(BaseModel):
    id: int
    name: str
    email: str

class AsyncWebapi(AsyncWrapper):
    """Your custom API client"""
    
    async def get_user(self, user_id: int) -> User:
        """Get user by ID"""
        return await self._request(
            "GET",
            f"/users/{user_id}",
            response_model=User
        )
    
    async def list_users(self) -> List[User]:
        """Get all users"""
        return await self._request(
            "GET",
            "/users",
            response_model=List[User]
        )
    
    async def create_user(self, name: str, email: str) -> User:
        """Create new user"""
        return await self._request(
            "POST",
            "/users",
            json={"name": name, "email":  email},
            response_model=User
        )
```

### Using Your API Client

```python
# Simple usage
client = AsyncWebapi(base_url="https://api.webapi.com")
result = await client.get_user(123)
await client.close()

# With custom adapter config
client = AsyncWebapi(
    base_url="https://api.webapi.com",
    timeout=30.0,
    max_retries=3,
    headers={"Authorization": "Bearer token"}
)

# With async context manager (recommended)
async with AsyncWebapi(base_url="https://api.webapi.com") as client:
    user = await client.get_user(123)
    users = await client.list_users()
```

### Synchronous Client Example

```python
from wrapper import SyncClientWrapper

class SyncWebapi(SyncClientWrapper):
    """Synchronous API client"""
    
    def get_user(self, user_id: int) -> User:
        return self._request(
            "GET",
            f"/users/{user_id}",
            response_model=User
        )

# Usage with context manager
with SyncWebapi(base_url="https://api.webapi.com") as client:
    user = client.get_user(123)
```

## Configuration Options

Both wrapper classes support the following parameters:

- **`base_url`** (required): Base URL for the API
- **`http_client`** (optional): Custom HTTP client adapter
- **`timeout`** (optional): Request timeout in seconds
- **`max_retries`** (optional): Maximum number of retry attempts
- **`headers`** (optional): Default headers for all requests
- **`verify`** (optional): SSL certificate verification (default: True)
- **`**adapter_kwargs`**: Additional adapter-specific parameters

## The `_request` Method

Both wrappers provide a `_request` method for making HTTP calls:

```python
async def _request(
    method: str,              # HTTP method: "GET", "POST", etc. 
    path: str,                # Endpoint path (e.g., "/users/123")
    response_model:  Optional[Type[T]] = None,  # Pydantic model for parsing
    **kwargs                  # Additional params:  json, params, headers, etc.
) -> T
```

**Parameters for `**kwargs`**:
- `params`: Query parameters (dict)
- `json`: JSON request body (dict)
- `data`: Form data or raw body
- `headers`: Request-specific headers (dict)
- `timeout`: Override default timeout

## Installation

```bash
pip install universal-http-api-client
```

## Requirements

- Python 3.9+
- httpx
- pydantic

## License

[Add your license here]

## Contributing

[Add contributing guidelines here]
