"""SQS Microflex connector for AWS SQS (Simple Queue Service)."""

import time
from typing import Iterator

import boto3
from botocore.exceptions import ClientError
from pyspark.sql.types import StructType

from databricks.labs.community_connector.interface import LakeflowConnect
from databricks.labs.community_connector.sources.sqs_microflex.sqs_microflex_schemas import (
    INITIAL_BACKOFF,
    MAX_RETRIES,
    MESSAGES_METADATA,
    MESSAGES_SCHEMA,
    QUEUES_METADATA,
    QUEUES_SCHEMA,
    parse_message,
    parse_queue_attributes,
)

# AWS error codes that are safe to retry with exponential backoff.
RETRIABLE_ERROR_CODES = {"RequestThrottled", "OverLimit", "InternalError", "ServiceUnavailable"}

SUPPORTED_TABLES = ["queues", "messages"]


class SqsMicroflexLakeflowConnect(LakeflowConnect):
    """LakeflowConnect implementation for AWS SQS."""

    def __init__(self, options: dict[str, str]) -> None:
        super().__init__(options)

        client_kwargs = {
            "service_name": "sqs",
            "region_name": options["aws_region"],
            "aws_access_key_id": options["aws_access_key_id"],
            "aws_secret_access_key": options["aws_secret_access_key"],
        }
        session_token = options.get("aws_session_token")
        if session_token:
            client_kwargs["aws_session_token"] = session_token

        self._client = boto3.client(**client_kwargs)

    # ------------------------------------------------------------------
    # Interface methods
    # ------------------------------------------------------------------

    def list_tables(self) -> list[str]:
        return list(SUPPORTED_TABLES)

    def get_table_schema(self, table_name: str, table_options: dict[str, str]) -> StructType:
        self._validate_table(table_name)
        if table_name == "queues":
            return QUEUES_SCHEMA
        return MESSAGES_SCHEMA

    def read_table_metadata(self, table_name: str, table_options: dict[str, str]) -> dict:
        self._validate_table(table_name)
        if table_name == "queues":
            return dict(QUEUES_METADATA)
        return dict(MESSAGES_METADATA)

    def read_table(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        self._validate_table(table_name)
        if table_name == "queues":
            return self._read_queues(table_options)
        return self._read_messages(start_offset, table_options)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_table(self, table_name: str) -> None:
        if table_name not in SUPPORTED_TABLES:
            raise ValueError(
                f"Table '{table_name}' is not supported. Supported tables: {SUPPORTED_TABLES}"
            )

    def _call_with_retry(self, api_method, **kwargs):
        """Call a boto3 SQS API method with exponential backoff on retriable errors."""
        backoff = INITIAL_BACKOFF
        for attempt in range(MAX_RETRIES):
            try:
                return api_method(**kwargs)
            except ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code not in RETRIABLE_ERROR_CODES:
                    raise
                if attempt < MAX_RETRIES - 1:
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise

    # ------------------------------------------------------------------
    # Queues table (snapshot)
    # ------------------------------------------------------------------

    def _list_all_queue_urls(self) -> list[str]:
        """Paginate through ListQueues to discover all queue URLs."""
        queue_urls = []
        params = {"MaxResults": 100}

        while True:
            resp = self._call_with_retry(self._client.list_queues, **params)
            queue_urls.extend(resp.get("QueueUrls", []))
            next_token = resp.get("NextToken")
            if not next_token:
                break
            params["NextToken"] = next_token

        return queue_urls

    def _read_queues(
        self, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        """Full-refresh read of all queues and their attributes."""
        queue_urls = self._list_all_queue_urls()

        records = []
        for queue_url in queue_urls:
            resp = self._call_with_retry(
                self._client.get_queue_attributes,
                QueueUrl=queue_url,
                AttributeNames=["All"],
            )
            attrs = resp.get("Attributes", {})
            records.append(parse_queue_attributes(queue_url, attrs))

        return iter(records), {}

    # ------------------------------------------------------------------
    # Messages table (append)
    # ------------------------------------------------------------------

    def _read_messages(
        self, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        """Read messages from all queues.

        Polling strategy:
        - Discover all queues via ListQueues.
        - For each queue, call ReceiveMessage repeatedly (max 10 per call)
          until an empty response is returned, which means the queue is
          drained for this polling cycle.
        - Messages are NOT deleted (non-destructive read).
        - Deduplication by message_id is handled via a seen-set so duplicate
          receives within the same batch are dropped.
        - The offset tracks the set of message_ids already ingested so the
          framework can detect "no new data" when the returned offset
          equals the start offset.
        """
        seen_ids: set[str] = set()
        if start_offset:
            # Rebuild seen-set from the previous offset so we can skip
            # messages that were already ingested in a prior batch.
            prev_ids = start_offset.get("seen_ids", [])
            seen_ids.update(prev_ids)

        queue_urls = self._list_all_queue_urls()

        records = []
        for queue_url in queue_urls:
            self._poll_queue(queue_url, records, seen_ids)

        if not records:
            return iter([]), start_offset or {}

        # Build end offset.  We store the union of previously-seen IDs and
        # newly-seen IDs so that on the next call the framework can detect
        # "no new data" (start_offset == end_offset).
        all_seen = list(seen_ids)
        end_offset = {"seen_ids": all_seen}

        if start_offset and start_offset == end_offset:
            return iter([]), start_offset

        return iter(records), end_offset

    def _poll_queue(
        self, queue_url: str, records: list[dict], seen_ids: set[str]
    ) -> None:
        """Receive all currently visible messages from a single queue."""
        while True:
            resp = self._call_with_retry(
                self._client.receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                MessageSystemAttributeNames=["All"],
                MessageAttributeNames=["All"],
                WaitTimeSeconds=1,
                VisibilityTimeout=30,
            )
            messages = resp.get("Messages", [])
            if not messages:
                break

            for msg in messages:
                mid = msg["MessageId"]
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                records.append(parse_message(msg, queue_url))
