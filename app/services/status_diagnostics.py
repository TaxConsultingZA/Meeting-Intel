"""Content-free, request-local timings for GET /recordings/jobs only."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy import event


log = logging.getLogger("uvicorn.error")
_current = ContextVar("recording_status_diagnostics", default=None)


@contextmanager
def measure(stage):
    timing = _current.get()
    if timing is None:
        yield
        return
    # Eager loaders invoke ORM execution recursively. Count the outer operation
    # once, including hydration, but subtract connection resolution separately.
    if timing["depth"].get(stage, 0):
        yield
        return
    timing["depth"][stage] = 1
    started = perf_counter()
    connection_before = timing["db_connection_ms"]
    try:
        yield
    finally:
        elapsed = (perf_counter() - started) * 1000
        if stage == "db_query_ms":
            elapsed -= timing["db_connection_ms"] - connection_before
        timing[stage] += max(0, elapsed)
        timing["depth"][stage] = 0


def authentication_timing(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        with measure("authentication_ms"):
            return await function(*args, **kwargs)
    return wrapped


def response_ready():
    timing = _current.get()
    if timing is not None:
        timing["serialization_started"] = perf_counter()


def install_database_timings(session_factory):
    @event.listens_for(session_factory.class_.sync_session_class, "do_orm_execute", retval=True)
    def execute(state):
        if _current.get() is None:
            return None
        # Resolve the same connection/bind the ORM operation would use. This
        # includes pool wait, pre-ping, connect and transaction setup, with no
        # extra SQL or commit. Reusing an existing connection is also timed.
        with measure("db_connection_ms"):
            state.session.connection(bind_arguments=state.bind_arguments)
        with measure("db_query_ms"):
            return state.invoke_statement()


class RecordingStatusRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def timed_handler(request):
            if request.method != "GET" or self.path != "/recordings/jobs":
                return await handler(request)
            started = perf_counter()
            timing = {"authentication_ms": 0.0, "db_session_ms": 0.0,
                      "db_connection_ms": 0.0, "db_query_ms": 0.0,
                      "serialization_started": None, "depth": {}}
            token = _current.set(timing)
            status = 500
            try:
                response = await handler(request)
                status = response.status_code
                return response
            except HTTPException as exc:
                status = exc.status_code
                raise
            except RequestValidationError:
                status = 422
                raise
            finally:
                finished = perf_counter()
                _current.reset(token)
                record = {"event": "recording_status_performance", "diagnostic_id": str(uuid4()),
                          "endpoint": "/recordings/jobs", "status_code": status,
                          "authentication_includes_database": True,
                          **{key: round(timing[key], 3) for key in (
                              "authentication_ms", "db_session_ms", "db_connection_ms", "db_query_ms")},
                          "serialization_ms": round((finished - timing["serialization_started"]) * 1000, 3)
                              if timing["serialization_started"] is not None else None,
                          "total_endpoint_ms": round((finished - started) * 1000, 3)}
                # Observability must never turn a successful request into an error.
                try:
                    log.info("recording_status_performance %s", json.dumps(record))
                except Exception:
                    pass
        return timed_handler
