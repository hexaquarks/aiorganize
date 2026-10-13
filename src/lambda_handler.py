"""Run the existing API behind an AWS Lambda Function URL."""

import os
from functools import cache

from mangum import Mangum

from .backend import create_app, store_from_environment


@cache
def application():
    store = store_from_environment()
    app = create_app(store, os.environ.get("APP_SIGNING_SECRET", ""))
    store.initialize()

    # Reuse the client and limiter between invocations. ASGI shutdown after each
    # request would close the shared connection. Limits apply per warm instance.
    return Mangum(app, lifespan="off")


def handler(event, context):
    return application()(event, context)
