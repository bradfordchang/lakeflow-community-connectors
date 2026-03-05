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
        self._client = None

    @property
    def client(self):
        """Lazily create the boto3 SQS client to avoid pickling thread locks."""
        if self._client is None:
            client_kwargs = {
                "service_name": "sqs",
                "region_name": self.options["aws_region"],
                "aws_access_key_id": self.options["aws_access_key_id"],
                "aws_secret_access_key": self.options["aws_secret_access_key"],
            }
            session_token = self.options.get("aws_session_token")
            if session_token:
                client_kwargs["aws_session_token"] = session_token
            self._client = boto3.client(**client_kwargs)
        return self._client

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
            resp = self._call_with_retry(self.client.list_queues, **params)
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
                self.client.get_queue_attributes,
                QueueUrl=queue_url,
                AttributeNames=["All"],
            )
            attrs = resp.get("Attributes", {})
            records.append(parse_queue_attributes(queue_url, attrs))

        return iter(records), {}

    # ------------------------------------------------------------------
    # Messages table (append)
    # ------------------------------------------------------------------

    # Maximum messages to read per micro-batch to avoid unbounded polling.
    MAX_BATCH_SIZE = 1000

    def _read_messages(
        self, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        """Read messages from all queues in bounded batches.

        Polling strategy:
        - Discover all queues via ListQueues.
        - For each queue, call ReceiveMessage repeatedly (max 10 per call)
          until MAX_BATCH_SIZE is reached or the queue returns no messages.
        - Messages are NOT deleted (non-destructive read).
        - The offset tracks the max sent_timestamp seen so the framework
          can detect progress between batches.
        """
        max_batch = int(table_options.get("max_records_per_batch", str(self.MAX_BATCH_SIZE)))
        last_ts = start_offset.get("last_sent_timestamp", "0") if start_offset else "0"

        queue_urls = self._list_all_queue_urls()

        records = []
        max_ts = last_ts
        for queue_url in queue_urls:
            if len(records) >= max_batch:
                break
            self._poll_queue(queue_url, records, max_batch - len(records))
            # Track the max sent_timestamp across all records
            for rec in records:
                ts = rec.get("sent_timestamp")
                if ts is not None:
                    ts_str = str(ts)
                    if ts_str > max_ts:
                        max_ts = ts_str

        if not records:
            return iter([]), start_offset or {}

        end_offset = {"last_sent_timestamp": max_ts}
        if start_offset and start_offset == end_offset:
            return iter([]), start_offset

        return iter(records), end_offset

    def _poll_queue(
        self, queue_url: str, records: list[dict], remaining: int
    ) -> None:
        """Receive messages from a single queue up to the remaining limit."""
        while remaining > 0:
            fetch_size = min(10, remaining)
            resp = self._call_with_retry(
                self.client.receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=fetch_size,
                MessageSystemAttributeNames=["All"],
                MessageAttributeNames=["All"],
                WaitTimeSeconds=1,
                VisibilityTimeout=5,
            )
            messages = resp.get("Messages", [])
            if not messages:
                break

            for msg in messages:
                records.append(parse_message(msg, queue_url))
                remaining -= 1
