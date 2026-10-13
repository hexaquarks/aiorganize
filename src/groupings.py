"""Validate and store approved groupings in the app owner's database."""

import json
from datetime import datetime
from typing import Annotated
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator
from qdrant_client import QdrantClient, models


COLLECTION = "aiorganize_groups_v1_text_embedding_3_small_1536"
EMBEDDING_MODEL = "text-embedding-3-small"
DIMENSIONS = 1536
Vector = Annotated[list[FiniteFloat], Field(min_length=DIMENSIONS, max_length=DIMENSIONS)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class Page(StrictModel):
    title: str = Field(max_length=4096)
    url: str = Field(max_length=8192)


class VectorInput(StrictModel):
    vector: Vector

    @field_validator("vector")
    @classmethod
    def nonzero_vector(cls, value):
        if not any(value):
            raise ValueError("A vector must be nonzero.")
        return value


class ApprovedGroup(VectorInput):
    name: str = Field(min_length=1, max_length=7)
    pages: list[Page] = Field(min_length=1, max_length=1000)
    approvedAt: datetime

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("A group needs a name.")
        return value


class SaveRequest(StrictModel):
    groups: list[ApprovedGroup] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def limit_total_pages(self):
        if sum(len(group.pages) for group in self.groups) > 1000:
            raise ValueError("Too many pages.")
        return self


class SearchRequest(VectorInput):
    limit: int = Field(default=5, ge=1, le=5)


class GroupingsStore:
    def __init__(self, client: QdrantClient, collection: str = COLLECTION):
        self.client = client
        self.collection = collection

    def initialize(self):
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(size=DIMENSIONS, distance=models.Distance.COSINE),
            )

        info = self.client.get_collection(self.collection)
        vectors = info.config.params.vectors
        if not isinstance(vectors, models.VectorParams) or vectors.size != DIMENSIONS:
            raise ValueError("Incompatible saved groupings collection.")
        if vectors.distance != models.Distance.COSINE:
            raise ValueError("Incompatible saved groupings distance.")

        indexes = {
            "userId": models.PayloadSchemaType.KEYWORD,
            "schemaVersion": models.PayloadSchemaType.INTEGER,
            "embeddingModel": models.PayloadSchemaType.KEYWORD,
            "embeddingDimensions": models.PayloadSchemaType.INTEGER,
        }
        for field, schema in indexes.items():
            existing = info.payload_schema.get(field)
            if existing and existing.data_type != schema:
                raise ValueError("Incompatible saved groupings index.")
            if not existing:
                self.client.create_payload_index(self.collection, field, schema, wait=True)

    def save(self, owner: str, request: SaveRequest):
        points = []
        for group in request.groups:
            pages = [page.model_dump() for page in group.pages]
            # Sort a copy so approval order stays intact, but retries have stable IDs.
            canonical = json.dumps(
                {"name": group.name, "pages": sorted(pages, key=lambda page: (page["title"], page["url"]))},
                ensure_ascii=False, separators=(",", ":"),
            )
            point_id = str(uuid5(NAMESPACE_URL, f"{self.collection}:{owner}:{canonical}"))
            points.append(models.PointStruct(id=point_id, vector=group.vector, payload={
                "userId": owner,
                "name": group.name,
                "pages": pages,
                "approvedAt": group.approvedAt.isoformat(),
                "schemaVersion": 1,
                "embeddingModel": EMBEDDING_MODEL,
                "embeddingDimensions": DIMENSIONS,
            }))

        result = self.client.upsert(self.collection, points, wait=True)
        if result.status != models.UpdateStatus.COMPLETED:
            raise RuntimeError("Database write was not confirmed.")
        return {"ids": [point.id for point in points]}

    def search(self, owner: str, request: SearchRequest):
        constraints = {
            "userId": owner, "schemaVersion": 1,
            "embeddingModel": EMBEDDING_MODEL, "embeddingDimensions": DIMENSIONS,
        }
        result = self.client.query_points(
            self.collection, query=request.vector, limit=request.limit,
            query_filter=models.Filter(must=[
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in constraints.items()
            ]),
            with_payload=True, with_vectors=False,
        )
        groups = []
        for point in result.points:
            payload = point.payload or {}
            if any(payload.get(key) != value for key, value in constraints.items()):
                continue
            # Return only model context, never database fields or another owner's records.
            pages = [Page.model_validate(page).model_dump() for page in payload["pages"][:5]]
            groups.append({"name": payload["name"], "pages": pages})
        return {"groups": groups}
