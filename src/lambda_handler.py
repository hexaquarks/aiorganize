"""Run the existing API behind AWS API Gateway and Lambda."""

import os
from functools import cache

from mangum import Mangum

from .backend import create_app, store_from_environment


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
    if len((event.get("body") or "").encode("utf-8")) > 1024 * 1024:
        return {"statusCode": 413, "body": '{"detail":"Request is too large."}'}

    return application()(event, context)
