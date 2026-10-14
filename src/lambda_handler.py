"""Run the existing API behind AWS API Gateway and Lambda."""

import os
from functools import cache
from http import HTTPStatus

from mangum import Mangum

from .api import create_app, store_from_environment

MAX_REQUEST_BYTES = 1024 * 1024


@cache
def application():
    store = store_from_environment()
    app = create_app(store, os.environ.get("APP_SIGNING_SECRET", ""))
    store.initialize()

    # Reuse clients between invocations. ASGI shutdown after each request would
    # close the shared connection.
    return Mangum(app, lifespan="off")


def handler(event, context):
    # Reject oversized bodies before JSON parsing or opening database connections.
    body = event.get("body") or ""
    body_size = len(body.encode("utf-8"))

    if body_size > MAX_REQUEST_BYTES:
        return {"statusCode": HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body": '{"detail":"Request is too large."}'}

    return application()(event, context)
