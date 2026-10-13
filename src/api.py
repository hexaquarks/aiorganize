"""HTTP endpoints for installation credentials and saved groupings."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from qdrant_client import QdrantClient

from .groupings import COLLECTION, GroupingsStore, SaveRequest, SearchRequest


logger = logging.getLogger(__name__)
router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def get_store(request: Request) -> GroupingsStore:
    return request.app.state.groupings


def installation_id(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    try:
        if not credentials or len(credentials.credentials) > 4096:
            raise ValueError("Missing installation credential.")

        claims = jwt.decode(
            credentials.credentials,
            request.app.state.signing_secret,
            algorithms=["HS256"],
            issuer="aiorganize",
            audience="saved-groupings",
            options={"require": ["sub", "iat", "iss", "aud"]},
        )

        return str(UUID(claims["sub"]))
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(401, "Invalid installation credential.") from None


@router.post("/v1/installations", status_code=201)
def register(request: Request):
    # Keep the signing secret stable across deployments so installations retain access.
    claims = {
        "sub": str(uuid4()),
        "iat": datetime.now(timezone.utc),
        "iss": "aiorganize",
        "aud": "saved-groupings",
    }
    token = jwt.encode(claims, request.app.state.signing_secret, algorithm="HS256")

    return {"token": token}


@router.post("/v1/groupings")
def save(
    body: SaveRequest,
    user: Annotated[str, Depends(installation_id)],
    store: Annotated[GroupingsStore, Depends(get_store)],
):
    try:
        return store.save(user, body)
    except Exception:
        logger.error("Saving groupings failed. Check the backend database connection.")
        raise HTTPException(503, "Saved groupings are temporarily unavailable.") from None


@router.post("/v1/groupings/search")
def search(
    body: SearchRequest,
    user: Annotated[str, Depends(installation_id)],
    store: Annotated[GroupingsStore, Depends(get_store)],
):
    try:
        return store.search(user, body)
    except Exception:
        logger.error("Retrieving groupings failed. Check the backend database connection.")
        raise HTTPException(503, "Saved groupings are temporarily unavailable.") from None


@router.get("/health")
def health():
    return {"status": "ok"}


async def invalid_request(request: Request, error: RequestValidationError):
    return JSONResponse({"detail": "Invalid grouping request."}, status_code=422)


def create_app(store: GroupingsStore, signing_secret: str) -> FastAPI:
    if len(signing_secret) < 32:
        raise ValueError("APP_SIGNING_SECRET must contain at least 32 random characters.")

    @asynccontextmanager
    async def lifespan(app):
        # Refuse to serve if the database cannot be reached or is incompatible.
        store.initialize()
        try:
            yield
        finally:
            store.client.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.groupings = store
    app.state.signing_secret = signing_secret
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.include_router(router)

    return app


def store_from_environment() -> GroupingsStore:
    endpoint = os.environ.get("QDRANT_ENDPOINT", "")
    key = os.environ.get("QDRANT_API_KEY", "")

    if not endpoint or not key:
        raise ValueError("Configure QDRANT_ENDPOINT and QDRANT_API_KEY on the backend.")

    client = QdrantClient(url=endpoint, api_key=key, timeout=30, check_compatibility=False)
    collection = os.environ.get("QDRANT_COLLECTION", COLLECTION)
    return GroupingsStore(client, collection)


def from_environment() -> FastAPI:
    return create_app(store_from_environment(), os.environ.get("APP_SIGNING_SECRET", ""))
