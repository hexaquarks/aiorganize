"""App-owned database API. Start with uvicorn src.backend:from_environment --factory."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from qdrant_client import QdrantClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .groupings import COLLECTION, GroupingsStore, SaveRequest, SearchRequest


logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def create_app(store: GroupingsStore, signing_secret: str) -> FastAPI:
    if len(signing_secret) < 32:
        raise ValueError("APP_SIGNING_SECRET must contain at least 32 random characters.")

    @asynccontextmanager
    async def lifespan(app):
        # Refuse to serve if the owner's database cannot be reached or is incompatible.
        store.initialize()
        try:
            yield
        finally:
            store.client.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({"detail": "Invalid grouping request."}, status_code=422)

    def owner(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        try:
            if not credentials or len(credentials.credentials) > 4096:
                raise ValueError("Missing installation credential.")

            claims = jwt.decode(
                credentials.credentials,
                signing_secret,
                algorithms=["HS256"],
                issuer="aiorganize",
                audience="saved-groupings",
                options={"require": ["sub", "iat", "iss", "aud"]},
            )

            return str(UUID(claims["sub"]))
        except (jwt.InvalidTokenError, ValueError, KeyError):
            raise HTTPException(401, "Invalid installation credential.") from None

    @app.post("/v1/installations", status_code=201)
    @limiter.limit("10/hour")
    def register(request: Request):
        # A persistent installation credential avoids accounts and sign-in. Keep the
        # signing secret stable across deployments; rotating it revokes these credentials.
        claims = {
            "sub": str(uuid4()),
            "iat": datetime.now(timezone.utc),
            "iss": "aiorganize",
            "aud": "saved-groupings",
        }
        token = jwt.encode(claims, signing_secret, algorithm="HS256")

        return {"token": token}

    @app.post("/v1/groupings")
    @limiter.limit("30/minute")
    def save(request: Request, body: SaveRequest, user: Annotated[str, Depends(owner)]):
        try:
            return store.save(user, body)
        except Exception:
            logger.error("Saving groupings failed. Check the backend database connection.")
            raise HTTPException(503, "Saved groupings are temporarily unavailable.") from None

    @app.post("/v1/groupings/search")
    @limiter.limit("60/minute")
    def search(request: Request, body: SearchRequest, user: Annotated[str, Depends(owner)]):
        try:
            return store.search(user, body)
        except Exception:
            logger.error("Retrieving groupings failed. Check the backend database connection.")
            raise HTTPException(503, "Saved groupings are temporarily unavailable.") from None

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def from_environment() -> FastAPI:
    endpoint = os.environ.get("QDRANT_ENDPOINT", "")
    key = os.environ.get("QDRANT_API_KEY", "")
    secret = os.environ.get("APP_SIGNING_SECRET", "")

    if not endpoint or not key:
        raise ValueError("Configure QDRANT_ENDPOINT and QDRANT_API_KEY on the backend.")

    client = QdrantClient(url=endpoint, api_key=key, timeout=30, check_compatibility=False)
    collection = os.environ.get("QDRANT_COLLECTION", COLLECTION)
    return create_app(GroupingsStore(client, collection), secret)
