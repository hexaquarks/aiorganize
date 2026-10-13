"""Shared request limits and installation revocation for the hosted API."""

import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException


class AccessControl:
    def __init__(self, table):
        self.table = table

    def allow(self, key: str, maximum: int, seconds: int, units: int = 1):
        if not 1 <= units <= maximum:
            raise HTTPException(429, "Please try again later.")

        window = int(time.time()) // seconds

        try:
            # A conditional update makes the limit atomic across Lambda instances.
            # Windowed keys remain correct even when DynamoDB TTL cleanup is delayed.
            self.table.update_item(
                Key={"id": f"limit:{key}:{window}"},
                UpdateExpression="SET expiresAt = :expires ADD hits :units",
                ConditionExpression="attribute_not_exists(hits) OR hits <= :remaining",
                ExpressionAttributeValues={
                    ":expires": (window + 2) * seconds,
                    ":units": units,
                    ":remaining": maximum - units,
                },
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                retry_after = (window + 1) * seconds - int(time.time())
                raise HTTPException(429, "Please try again later.", headers={"Retry-After": str(retry_after)}) from None
            raise HTTPException(503, "Saved groupings are temporarily unavailable.") from None
        except BotoCoreError:
            raise HTTPException(503, "Saved groupings are temporarily unavailable.") from None

    def check_installation(self, owner: str):
        try:
            result = self.table.get_item(Key={"id": f"revoked:{owner}"}, ConsistentRead=True)
        except (BotoCoreError, ClientError):
            raise HTTPException(503, "Saved groupings are temporarily unavailable.") from None

        if "Item" in result:
            raise HTTPException(401, "Invalid installation credential.")


def from_environment() -> AccessControl:
    table_name = os.environ.get("ACCESS_TABLE", "")
    if not table_name:
        raise ValueError("Configure ACCESS_TABLE on the hosted backend.")

    config = Config(connect_timeout=3, read_timeout=3, retries={"mode": "standard", "total_max_attempts": 2})
    database = boto3.resource("dynamodb", config=config)
    return AccessControl(database.Table(table_name))
