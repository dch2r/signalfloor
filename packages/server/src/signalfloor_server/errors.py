"""Error responses."""

import math
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

MAX_ECHOED_STRING = 100


async def validation_error(request: Request, exc: Exception) -> JSONResponse:
    """The default 422 response, with the echoed input made safe.

    Each validation error echoes the input it rejected. Two problems with that:

    - A score of NaN, Infinity or 1e999 can't be written as JSON, so the default handler crashed
      and the client got a 500 instead of a 422.
    - An upload with too many cases got every case echoed back, a 2.5 MB error for a 2.9 MB
      request.

    So only small single values are echoed. Lists and objects are left out and long strings are
    cut short.
    """
    assert isinstance(exc, RequestValidationError)
    errors = []
    for error in jsonable_encoder(exc.errors()):
        input_ = _small(error.pop("input", None))
        if input_ is not _OMIT:
            error["input"] = input_
        errors.append(error)
    return JSONResponse(status_code=422, content={"detail": errors})


_OMIT = object()


def _small(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, str) and len(value) > MAX_ECHOED_STRING:
        return value[:MAX_ECHOED_STRING] + "..."
    if isinstance(value, dict | list):
        return _OMIT
    return value
