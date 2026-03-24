from typing import Any, Optional, Type, TypeVar, List as ListType
import typing

from pydantic import BaseModel

try:
    from .adapters import HttpResponse, HttpError
except ImportError:
    from adapters import HttpResponse, HttpError  # type: ignore

T = TypeVar("T", bound=BaseModel)
ParsedResponse = T | list[T] | HttpResponse | Any


def parse_response_model(
    response: HttpResponse,
    path: str,
    response_model: Optional[Type[T] | Type[ListType[T]]] = None,
) -> ParsedResponse:
    """Parse a normalized response into a Pydantic model or list of models."""
    if response_model is None:
        return response

    try:
        data = response.json()
    except ValueError as exc:
        status = response.status_code
        if status == 404:
            raise HttpError(status, f"Endpoint not found (404): {path}") from exc
        if status in (401, 403):
            raise HttpError(status, f"Unauthorized ({status}): {path}") from exc
        if status >= 500:
            raise HttpError(status, f"Server error ({status}): {path}") from exc
        raise HttpError(
            status,
            f"Failed to parse JSON response from {path}: {exc}\n"
            f"Response status: {status}\n"
            f"Response body: {response.content}",
        ) from exc

    try:
        origin = typing.get_origin(response_model)
        if origin is list:
            args = typing.get_args(response_model)
            if args and isinstance(data, list):
                item_model = args[0]
                if not hasattr(item_model, "model_validate"):
                    return data
                return [item_model.model_validate(item) for item in data]

        return response_model.model_validate(data)
    except Exception as exc:
        raise HttpError(
            response.status_code,
            f"Failed to validate response model for {path}: {exc}\n"
            f"Expected model: {response_model.__name__ if hasattr(response_model, '__name__') else response_model}\n"
            f"Got data: {data}",
        ) from exc
