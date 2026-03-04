"""Schemas, metadata, and constants for the SQS Microflex connector."""

import json

from pyspark.sql.types import (
    BooleanType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# ---------------------------------------------------------------------------
# Queues table schema
# ---------------------------------------------------------------------------
QUEUES_SCHEMA = StructType(
    [
        StructField("queue_url", StringType(), nullable=False),
        StructField("queue_name", StringType(), nullable=True),
        StructField("queue_arn", StringType(), nullable=True),
        StructField("approximate_number_of_messages", LongType(), nullable=True),
        StructField("approximate_number_of_messages_not_visible", LongType(), nullable=True),
        StructField("approximate_number_of_messages_delayed", LongType(), nullable=True),
        StructField("created_timestamp", TimestampType(), nullable=True),
        StructField("last_modified_timestamp", TimestampType(), nullable=True),
        StructField("visibility_timeout", LongType(), nullable=True),
        StructField("maximum_message_size", LongType(), nullable=True),
        StructField("message_retention_period", LongType(), nullable=True),
        StructField("delay_seconds", LongType(), nullable=True),
        StructField("receive_message_wait_time_seconds", LongType(), nullable=True),
        StructField("policy", StringType(), nullable=True),
        StructField("redrive_policy", StringType(), nullable=True),
        StructField("redrive_allow_policy", StringType(), nullable=True),
        StructField("fifo_queue", BooleanType(), nullable=True),
        StructField("content_based_deduplication", BooleanType(), nullable=True),
        StructField("deduplication_scope", StringType(), nullable=True),
        StructField("fifo_throughput_limit", StringType(), nullable=True),
        StructField("kms_master_key_id", StringType(), nullable=True),
        StructField("kms_data_key_reuse_period_seconds", LongType(), nullable=True),
        StructField("sqs_managed_sse_enabled", BooleanType(), nullable=True),
    ]
)

QUEUES_METADATA = {
    "primary_keys": ["queue_url"],
    "cursor_field": "",
    "ingestion_type": "snapshot",
}

# ---------------------------------------------------------------------------
# Messages table schema
# ---------------------------------------------------------------------------
MESSAGES_SCHEMA = StructType(
    [
        StructField("message_id", StringType(), nullable=False),
        StructField("queue_url", StringType(), nullable=True),
        StructField("receipt_handle", StringType(), nullable=True),
        StructField("body", StringType(), nullable=True),
        StructField("md5_of_body", StringType(), nullable=True),
        StructField("md5_of_message_attributes", StringType(), nullable=True),
        StructField("sender_id", StringType(), nullable=True),
        StructField("sent_timestamp", TimestampType(), nullable=True),
        StructField("approximate_receive_count", LongType(), nullable=True),
        StructField("approximate_first_receive_timestamp", TimestampType(), nullable=True),
        StructField("sequence_number", StringType(), nullable=True),
        StructField("message_deduplication_id", StringType(), nullable=True),
        StructField("message_group_id", StringType(), nullable=True),
        StructField("aws_trace_header", StringType(), nullable=True),
        StructField("dead_letter_queue_source_arn", StringType(), nullable=True),
        StructField("message_attributes", StringType(), nullable=True),
    ]
)

MESSAGES_METADATA = {
    "primary_keys": ["message_id"],
    "cursor_field": "sent_timestamp",
    "ingestion_type": "append",
}

# ---------------------------------------------------------------------------
# Retry constants
# ---------------------------------------------------------------------------
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0  # seconds; doubled after each retry

# ---------------------------------------------------------------------------
# AWS attribute-name-to-field-name mapping for queues
# ---------------------------------------------------------------------------
QUEUE_ATTR_MAP = {
    "QueueArn": "queue_arn",
    "ApproximateNumberOfMessages": "approximate_number_of_messages",
    "ApproximateNumberOfMessagesNotVisible": "approximate_number_of_messages_not_visible",
    "ApproximateNumberOfMessagesDelayed": "approximate_number_of_messages_delayed",
    "CreatedTimestamp": "created_timestamp",
    "LastModifiedTimestamp": "last_modified_timestamp",
    "VisibilityTimeout": "visibility_timeout",
    "MaximumMessageSize": "maximum_message_size",
    "MessageRetentionPeriod": "message_retention_period",
    "DelaySeconds": "delay_seconds",
    "ReceiveMessageWaitTimeSeconds": "receive_message_wait_time_seconds",
    "Policy": "policy",
    "RedrivePolicy": "redrive_policy",
    "RedriveAllowPolicy": "redrive_allow_policy",
    "FifoQueue": "fifo_queue",
    "ContentBasedDeduplication": "content_based_deduplication",
    "DeduplicationScope": "deduplication_scope",
    "FifoThroughputLimit": "fifo_throughput_limit",
    "KmsMasterKeyId": "kms_master_key_id",
    "KmsDataKeyReusePeriodSeconds": "kms_data_key_reuse_period_seconds",
    "SqsManagedSseEnabled": "sqs_managed_sse_enabled",
}

# Fields that should be parsed as integers
QUEUE_INT_FIELDS = {
    "approximate_number_of_messages",
    "approximate_number_of_messages_not_visible",
    "approximate_number_of_messages_delayed",
    "created_timestamp",
    "last_modified_timestamp",
    "visibility_timeout",
    "maximum_message_size",
    "message_retention_period",
    "delay_seconds",
    "receive_message_wait_time_seconds",
    "kms_data_key_reuse_period_seconds",
}

# Fields that should be parsed as booleans (from string "true"/"false")
QUEUE_BOOL_FIELDS = {
    "fifo_queue",
    "content_based_deduplication",
    "sqs_managed_sse_enabled",
}


def parse_queue_attributes(queue_url: str, attrs: dict) -> dict:
    """Convert raw AWS GetQueueAttributes response into a connector record dict."""
    queue_name = queue_url.rstrip("/").split("/")[-1]
    record = {
        "queue_url": queue_url,
        "queue_name": queue_name,
    }

    for aws_name, field_name in QUEUE_ATTR_MAP.items():
        raw = attrs.get(aws_name)
        if raw is None:
            record[field_name] = None
            continue

        if field_name in QUEUE_BOOL_FIELDS:
            record[field_name] = raw.lower() == "true"
        elif field_name in QUEUE_INT_FIELDS:
            record[field_name] = int(raw)
        else:
            record[field_name] = raw

    return record


def parse_message(msg: dict, queue_url: str) -> dict:
    """Convert a raw SQS ReceiveMessage response message into a connector record dict."""
    sys_attrs = msg.get("Attributes", {})
    user_attrs = msg.get("MessageAttributes", {})

    # Serialize user message attributes to a JSON string for storage.
    # Each attribute has StringValue/BinaryValue/DataType — we keep only
    # the string-representable parts.
    serialized_attrs = None
    if user_attrs:
        simplified = {}
        for k, v in user_attrs.items():
            simplified[k] = {
                "DataType": v.get("DataType", ""),
                "StringValue": v.get("StringValue"),
            }
        serialized_attrs = json.dumps(simplified)

    sent_ts_raw = sys_attrs.get("SentTimestamp")
    sent_ts = int(sent_ts_raw) / 1000.0 if sent_ts_raw else None

    first_recv_raw = sys_attrs.get("ApproximateFirstReceiveTimestamp")
    first_recv_ts = int(first_recv_raw) / 1000.0 if first_recv_raw else None

    recv_count_raw = sys_attrs.get("ApproximateReceiveCount")
    recv_count = int(recv_count_raw) if recv_count_raw else None

    return {
        "message_id": msg["MessageId"],
        "queue_url": queue_url,
        "receipt_handle": msg.get("ReceiptHandle"),
        "body": msg.get("Body"),
        "md5_of_body": msg.get("MD5OfBody"),
        "md5_of_message_attributes": msg.get("MD5OfMessageAttributes"),
        "sender_id": sys_attrs.get("SenderId"),
        "sent_timestamp": sent_ts,
        "approximate_receive_count": recv_count,
        "approximate_first_receive_timestamp": first_recv_ts,
        "sequence_number": sys_attrs.get("SequenceNumber"),
        "message_deduplication_id": sys_attrs.get("MessageDeduplicationId"),
        "message_group_id": sys_attrs.get("MessageGroupId"),
        "aws_trace_header": sys_attrs.get("AWSTraceHeader"),
        "dead_letter_queue_source_arn": sys_attrs.get("DeadLetterQueueSourceArn"),
        "message_attributes": serialized_attrs,
    }
