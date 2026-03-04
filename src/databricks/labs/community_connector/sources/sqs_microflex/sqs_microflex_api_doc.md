# AWS SQS (Simple Queue Service) API Documentation

**Source name:** `sqs_microflex`
**Tables in scope:** `messages`, `queues`
**API version:** AWS SQS JSON 1.0 protocol (current/stable)
**boto3 version referenced:** 1.42.x (latest stable as of research date)

---

## Authorization

### Preferred Method: IAM Access Key Credentials (passed explicitly via boto3)

AWS SQS uses AWS Signature Version 4 (SigV4) for all API requests. The connector stores three required and one optional credential:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `aws_access_key_id` | Yes | IAM user access key ID (e.g., `AKIA...`) |
| `aws_secret_access_key` | Yes | IAM user secret access key |
| `aws_region` | Yes | AWS region where queues reside (e.g., `us-east-1`) |
| `aws_session_token` | No | Temporary session token (required when using STS/assumed roles) |

All requests must be made over HTTPS. Requests without SigV4 signing return `InvalidSecurity` (HTTP 400).

### Minimum Required IAM Policy

The IAM user or role must have the following permissions at minimum:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SQSReadQueues",
      "Effect": "Allow",
      "Action": [
        "sqs:ListQueues"
      ],
      "Resource": "arn:aws:sqs:REGION:ACCOUNT_ID:*"
    },
    {
      "Sid": "SQSReadMessages",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl"
      ],
      "Resource": "arn:aws:sqs:REGION:ACCOUNT_ID:QUEUE_NAME"
    }
  ]
}
```

Note: `sqs:ListQueues` requires a wildcard resource ARN because it is a regional, non-queue-specific action. Cross-account permissions do not apply to `ListQueues`.

### boto3 Python Client Initialization

```python
import boto3

# Explicit credentials (preferred for connectors storing credentials)
client = boto3.client(
    'sqs',
    region_name='us-east-1',
    aws_access_key_id='YOUR_ACCESS_KEY_ID',
    aws_secret_access_key='YOUR_SECRET_ACCESS_KEY',
    aws_session_token='AQoXnyc4lcK4w...'  # optional, for temporary credentials
)
```

### Alternative Auth Methods (not preferred for this connector)

- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`)
- Shared credentials file (`~/.aws/credentials`)
- EC2/ECS/Lambda instance role (not portable across environments)

---

## Object List

### Static vs. Dynamic

The object list for this connector is **semi-static**: the two table types (`messages`, `queues`) are fixed, but the set of SQS queues is dynamic and retrieved via the `ListQueues` API.

### Tables

| Table | Description | Source |
|-------|-------------|--------|
| `queues` | Metadata and attributes for each SQS queue in the account/region | Retrieved via `ListQueues` + `GetQueueAttributes` |
| `messages` | Individual messages received from one or more SQS queues | Retrieved via `ReceiveMessage` per queue |

### Queue Discovery (for `messages` table)

The `messages` table requires a queue URL as input. Queues are enumerated via `ListQueues` and can be filtered by `QueueNamePrefix`. Each queue is polled independently.

**ListQueues API:**

```
POST / HTTP/1.1
Host: sqs.{region}.amazonaws.com
X-Amz-Target: AmazonSQS.ListQueues
Content-Type: application/x-amz-json-1.0

{
    "QueueNamePrefix": "my-prefix",
    "MaxResults": 100
}
```

**boto3 example:**

```python
response = client.list_queues(
    QueueNamePrefix='',   # optional prefix filter
    MaxResults=100        # required to enable NextToken pagination
)
queue_urls = response.get('QueueUrls', [])
next_token = response.get('NextToken')
```

---

## Object Schema

### Table: `queues`

Schema is static (defined by the `GetQueueAttributes` API). Each row represents one SQS queue.

**How to retrieve:** Call `ListQueues` to get queue URLs, then call `GetQueueAttributes` with `AttributeNames=["All"]` for each URL.

**GetQueueAttributes request:**

```python
response = client.get_queue_attributes(
    QueueUrl='https://sqs.us-east-1.amazonaws.com/177715257436/MyQueue',
    AttributeNames=['All']
)
attributes = response['Attributes']
```

**Example response:**

```json
{
    "Attributes": {
        "QueueArn": "arn:aws:sqs:us-east-1:177715257436:MyQueue",
        "ApproximateNumberOfMessages": "42",
        "ApproximateNumberOfMessagesNotVisible": "5",
        "ApproximateNumberOfMessagesDelayed": "0",
        "CreatedTimestamp": "1520621625",
        "LastModifiedTimestamp": "1520621706",
        "VisibilityTimeout": "30",
        "MaximumMessageSize": "262144",
        "MessageRetentionPeriod": "345600",
        "DelaySeconds": "0",
        "ReceiveMessageWaitTimeSeconds": "0",
        "Policy": "{...}",
        "RedrivePolicy": "{\"deadLetterTargetArn\":\"arn:aws:sqs:...\",\"maxReceiveCount\":10}",
        "FifoQueue": "false",
        "ContentBasedDeduplication": "false",
        "KmsMasterKeyId": "alias/aws/sqs",
        "KmsDataKeyReusePeriodSeconds": "300",
        "SqsManagedSseEnabled": "true"
    }
}
```

**Full `queues` table schema:**

| Field | AWS Attribute Name | Type | Description |
|-------|--------------------|------|-------------|
| `queue_url` | (from ListQueues) | string | Full URL of the queue (primary key) |
| `queue_name` | (derived from URL) | string | Queue name (last path segment of URL) |
| `queue_arn` | `QueueArn` | string | Amazon Resource Name |
| `approximate_number_of_messages` | `ApproximateNumberOfMessages` | integer | Approx. number of visible messages |
| `approximate_number_of_messages_not_visible` | `ApproximateNumberOfMessagesNotVisible` | integer | In-flight messages (received but not deleted) |
| `approximate_number_of_messages_delayed` | `ApproximateNumberOfMessagesDelayed` | integer | Delayed messages not yet available |
| `created_timestamp` | `CreatedTimestamp` | timestamp | Queue creation time (epoch seconds) |
| `last_modified_timestamp` | `LastModifiedTimestamp` | timestamp | Last modification time (epoch seconds) |
| `visibility_timeout` | `VisibilityTimeout` | integer | Default visibility timeout in seconds |
| `maximum_message_size` | `MaximumMessageSize` | integer | Max message size in bytes (up to 1,048,576) |
| `message_retention_period` | `MessageRetentionPeriod` | integer | Message retention in seconds (60–1,209,600) |
| `delay_seconds` | `DelaySeconds` | integer | Default delivery delay in seconds (0–900) |
| `receive_message_wait_time_seconds` | `ReceiveMessageWaitTimeSeconds` | integer | Long poll wait time in seconds (0–20) |
| `policy` | `Policy` | string (JSON) | Queue access policy JSON string |
| `redrive_policy` | `RedrivePolicy` | string (JSON) | Dead-letter queue config JSON string |
| `redrive_allow_policy` | `RedriveAllowPolicy` | string (JSON) | DLQ redrive permission policy JSON |
| `fifo_queue` | `FifoQueue` | boolean | Whether queue is FIFO type |
| `content_based_deduplication` | `ContentBasedDeduplication` | boolean | FIFO: content-based dedup enabled |
| `deduplication_scope` | `DeduplicationScope` | string | FIFO high-throughput: `messageGroup` or `queue` |
| `fifo_throughput_limit` | `FifoThroughputLimit` | string | FIFO high-throughput: `perQueue` or `perMessageGroupId` |
| `kms_master_key_id` | `KmsMasterKeyId` | string | KMS key ID for SSE (if configured) |
| `kms_data_key_reuse_period_seconds` | `KmsDataKeyReusePeriodSeconds` | integer | KMS data key reuse period |
| `sqs_managed_sse_enabled` | `SqsManagedSseEnabled` | boolean | Whether SSE-SQS encryption is enabled |

Note: Not all attributes are present for every queue. FIFO-specific attributes only appear when `FifoQueue=true`. KMS attributes only appear when KMS encryption is configured.

---

### Table: `messages`

Schema is semi-static; custom `MessageAttributes` vary by producer. Core message fields are always present.

**How to retrieve:** Call `ReceiveMessage` with `MessageSystemAttributeNames=["All"]` and `MessageAttributeNames=["All"]` per queue URL.

**Full `messages` table schema:**

| Field | Source | Type | Description |
|-------|--------|------|-------------|
| `message_id` | `MessageId` | string | Globally unique message ID (primary key) |
| `queue_url` | (request param) | string | URL of queue this message came from |
| `receipt_handle` | `ReceiptHandle` | string | Opaque identifier for delete/visibility operations |
| `body` | `Body` | string | Raw message body (XML, JSON, or plain text; max 256 KB) |
| `md5_of_body` | `MD5OfBody` | string | MD5 digest of Body for integrity verification |
| `md5_of_message_attributes` | `MD5OfMessageAttributes` | string | MD5 digest of MessageAttributes (if present) |
| `sender_id` | `Attributes.SenderId` | string | IAM user ID or role ID of message sender |
| `sent_timestamp` | `Attributes.SentTimestamp` | timestamp | Time message was sent (epoch milliseconds) |
| `approximate_receive_count` | `Attributes.ApproximateReceiveCount` | integer | Number of times message received but not deleted |
| `approximate_first_receive_timestamp` | `Attributes.ApproximateFirstReceiveTimestamp` | timestamp | First receive time (epoch milliseconds) |
| `sequence_number` | `Attributes.SequenceNumber` | string | FIFO sequence number (FIFO queues only) |
| `message_deduplication_id` | `Attributes.MessageDeduplicationId` | string | Dedup ID from SendMessage (FIFO only) |
| `message_group_id` | `Attributes.MessageGroupId` | string | Group ID from SendMessage (FIFO only) |
| `aws_trace_header` | `Attributes.AWSTraceHeader` | string | AWS X-Ray trace header string |
| `dead_letter_queue_source_arn` | `Attributes.DeadLetterQueueSourceArn` | string | Source queue ARN if message came from DLQ |
| `message_attributes` | `MessageAttributes` | map (JSON) | Custom key-value attributes set by the producer |

**`MessageAttributes` sub-structure** (per attribute):

| Sub-field | Type | Description |
|-----------|------|-------------|
| `StringValue` | string | Value if DataType is `String` or `Number` |
| `BinaryValue` | bytes | Value if DataType is `Binary` |
| `DataType` | string | One of: `String`, `Number`, `Binary` (plus optional suffix e.g. `String.email`) |

---

## Get Object Primary Keys

### `queues` table

**Primary key:** `queue_url`

Each queue has a globally unique URL within an AWS account and region. The URL is stable and does not change unless the queue is deleted and recreated.

Example: `https://sqs.us-east-1.amazonaws.com/177715257436/MyQueue`

### `messages` table

**Primary key:** `message_id`

`MessageId` is unique across all queues in all AWS accounts. Note: the same message may appear with the same `MessageId` across multiple `ReceiveMessage` calls if the visibility timeout expires before deletion. The connector must handle deduplication.

---

## Object Ingestion Type

### `queues` table

**Ingestion type: `snapshot`**

Queue attributes (message counts, timestamps, settings) can change at any time. There is no change-feed or cursor available for detecting queue attribute changes. The entire queue list must be re-fetched each sync. The `LastModifiedTimestamp` attribute could serve as a cursor in theory, but the API does not support filtering by it.

### `messages` table

**Ingestion type: `append`**

SQS is fundamentally a message queue with destructive reads: once a message is received and deleted, it is gone. The connector can only read messages that are currently in the queue (not yet deleted). New messages are appended; there is no changelog of deleted messages. `SentTimestamp` (epoch ms) can serve as an ordering field but cannot be used as a filter — the API does not support timestamp-based filtering on `ReceiveMessage`.

**Important behavioral note:** SQS does not support seeking or replaying messages. The connector reads whatever is currently available in the queue. If a message is received but not deleted, it becomes invisible for the `VisibilityTimeout` period and then reappears. For a read-only connector that should not consume/delete messages, use a large `VisibilityTimeout` and do NOT delete messages after reading. Alternatively, use a dedicated "shadow queue" or enable S3 archival.

**Assumption:** The connector will use a non-destructive read pattern (receive messages without deleting them), relying on `VisibilityTimeout` to return messages to the queue. This limits throughput to what fits in a single polling cycle unless messages are re-received after timeout expiry.

---

## Read API for Data Retrieval

### Reading `queues` Table

**Step 1 — List all queues:**

```python
def list_all_queues(client, queue_name_prefix=''):
    queues = []
    params = {'MaxResults': 100}
    if queue_name_prefix:
        params['QueueNamePrefix'] = queue_name_prefix

    while True:
        response = client.list_queues(**params)
        queues.extend(response.get('QueueUrls', []))
        next_token = response.get('NextToken')
        if not next_token:
            break
        params['NextToken'] = next_token

    return queues
```

**Step 2 — Fetch attributes per queue:**

```python
def get_queue_row(client, queue_url):
    response = client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=['All']
    )
    attrs = response.get('Attributes', {})
    # Derive queue_name from URL
    queue_name = queue_url.rstrip('/').split('/')[-1]
    return {
        'queue_url': queue_url,
        'queue_name': queue_name,
        'queue_arn': attrs.get('QueueArn'),
        'approximate_number_of_messages': int(attrs.get('ApproximateNumberOfMessages', 0)),
        'approximate_number_of_messages_not_visible': int(attrs.get('ApproximateNumberOfMessagesNotVisible', 0)),
        'approximate_number_of_messages_delayed': int(attrs.get('ApproximateNumberOfMessagesDelayed', 0)),
        'created_timestamp': int(attrs.get('CreatedTimestamp', 0)),
        'last_modified_timestamp': int(attrs.get('LastModifiedTimestamp', 0)),
        'visibility_timeout': int(attrs.get('VisibilityTimeout', 30)),
        'maximum_message_size': int(attrs.get('MaximumMessageSize', 262144)),
        'message_retention_period': int(attrs.get('MessageRetentionPeriod', 345600)),
        'delay_seconds': int(attrs.get('DelaySeconds', 0)),
        'receive_message_wait_time_seconds': int(attrs.get('ReceiveMessageWaitTimeSeconds', 0)),
        'policy': attrs.get('Policy'),
        'redrive_policy': attrs.get('RedrivePolicy'),
        'redrive_allow_policy': attrs.get('RedriveAllowPolicy'),
        'fifo_queue': attrs.get('FifoQueue', 'false').lower() == 'true',
        'content_based_deduplication': attrs.get('ContentBasedDeduplication', 'false').lower() == 'true',
        'deduplication_scope': attrs.get('DeduplicationScope'),
        'fifo_throughput_limit': attrs.get('FifoThroughputLimit'),
        'kms_master_key_id': attrs.get('KmsMasterKeyId'),
        'kms_data_key_reuse_period_seconds': int(attrs['KmsDataKeyReusePeriodSeconds']) if 'KmsDataKeyReusePeriodSeconds' in attrs else None,
        'sqs_managed_sse_enabled': attrs.get('SqsManagedSseEnabled', 'false').lower() == 'true',
    }
```

**Pagination:** `ListQueues` uses `NextToken`. Must set `MaxResults` (1–1000) to receive `NextToken` in the response. If `MaxResults` is not set, API returns up to 1000 results but does NOT return `NextToken` even if there are more.

---

### Reading `messages` Table

**Core receive loop (non-destructive — does NOT delete messages):**

```python
def receive_messages(client, queue_url, max_per_call=10, wait_seconds=10, visibility_timeout=30):
    """
    Receives up to max_per_call messages from queue_url.
    Uses long polling (wait_seconds > 0) for efficiency.
    Does NOT delete messages — they return to queue after visibility_timeout.
    """
    response = client.receive_message(
        QueueUrl=queue_url,
        MessageSystemAttributeNames=['All'],
        MessageAttributeNames=['All'],
        MaxNumberOfMessages=max_per_call,  # 1-10
        VisibilityTimeout=visibility_timeout,
        WaitTimeSeconds=wait_seconds        # 0-20; >0 enables long polling
    )
    return response.get('Messages', [])


def parse_message(msg, queue_url):
    attrs = msg.get('Attributes', {})
    return {
        'message_id': msg['MessageId'],
        'queue_url': queue_url,
        'receipt_handle': msg['ReceiptHandle'],
        'body': msg['Body'],
        'md5_of_body': msg.get('MD5OfBody'),
        'md5_of_message_attributes': msg.get('MD5OfMessageAttributes'),
        'sender_id': attrs.get('SenderId'),
        'sent_timestamp': int(attrs['SentTimestamp']) if 'SentTimestamp' in attrs else None,
        'approximate_receive_count': int(attrs.get('ApproximateReceiveCount', 1)),
        'approximate_first_receive_timestamp': int(attrs['ApproximateFirstReceiveTimestamp']) if 'ApproximateFirstReceiveTimestamp' in attrs else None,
        'sequence_number': attrs.get('SequenceNumber'),
        'message_deduplication_id': attrs.get('MessageDeduplicationId'),
        'message_group_id': attrs.get('MessageGroupId'),
        'aws_trace_header': attrs.get('AWSTraceHeader'),
        'dead_letter_queue_source_arn': attrs.get('DeadLetterQueueSourceArn'),
        'message_attributes': msg.get('MessageAttributes', {}),
    }
```

**Polling strategy for connector:**

SQS does not support cursor-based or timestamp-filtered reads. The connector must poll continuously:

```python
import time

def poll_queue(client, queue_url, batch_size=10, poll_interval_seconds=5):
    """
    Polls a single queue in a loop. Yields parsed message dicts.
    For an append-only connector, call this until the queue is drained
    (response returns empty Messages list).
    """
    while True:
        messages = receive_messages(client, queue_url, max_per_call=batch_size)
        if not messages:
            break  # Queue drained for this sync cycle
        for msg in messages:
            yield parse_message(msg, queue_url)
        time.sleep(poll_interval_seconds)
```

**Parameters:**

| Parameter | Required | Default | Range | Description |
|-----------|----------|---------|-------|-------------|
| `QueueUrl` | Yes | — | — | URL of queue to read from |
| `MaxNumberOfMessages` | No | 1 | 1–10 | Max messages per API call |
| `VisibilityTimeout` | No | Queue default (30s) | 0s–12h | How long messages stay invisible |
| `WaitTimeSeconds` | No | 0 | 0–20 | Long poll wait time; 0 = short poll |
| `MessageSystemAttributeNames` | No | [] | — | Use `["All"]` to get all system attrs |
| `MessageAttributeNames` | No | [] | — | Use `["All"]` to get all custom attrs |
| `ReceiveRequestAttemptId` | No | — | — | FIFO only: dedup token for retries |

**Short poll vs. long poll:**
- Short poll (default, `WaitTimeSeconds=0`): queries a random subset of servers, may return empty even when messages exist.
- Long poll (`WaitTimeSeconds=1–20`): waits for a message to arrive or timeout; reduces empty responses and API costs. Recommended for connectors.

**Throughput and rate limits:**

| Queue Type | ReceiveMessage limit |
|------------|----------------------|
| Standard | Nearly unlimited (no published TPS cap) |
| FIFO (without batching) | 300 API calls/sec |
| FIFO (with 10-message batching) | 3,000 messages/sec effective |

Additional constraints:
- Maximum 10 messages per `ReceiveMessage` call (hard limit)
- Maximum 120,000 in-flight messages per standard queue (20,000 for FIFO)
- `OverLimit` error returned if in-flight limit is exceeded
- `RequestThrottled` (HTTP 400) returned when rate limits are exceeded; implement exponential backoff

**Recommended retry strategy:** Exponential backoff with jitter starting at 1 second, up to 32 seconds, max 5 retries before failing.

---

## Field Type Mapping

### API types to Spark/Python types

| AWS/API Field | API Format | Python Type | Spark SQL Type | Notes |
|---------------|------------|-------------|----------------|-------|
| `MessageId` | string (UUID-like) | `str` | `StringType` | |
| `QueueUrl` | string (URL) | `str` | `StringType` | |
| `ReceiptHandle` | string (opaque) | `str` | `StringType` | Can be very long |
| `Body` | string | `str` | `StringType` | May contain JSON; parse downstream |
| `MD5OfBody` | string (hex) | `str` | `StringType` | |
| `SentTimestamp` | string (epoch ms) | `int` → `datetime` | `TimestampType` | Divide by 1000 for epoch seconds |
| `ApproximateFirstReceiveTimestamp` | string (epoch ms) | `int` → `datetime` | `TimestampType` | Divide by 1000 for epoch seconds |
| `ApproximateReceiveCount` | string (integer) | `int` | `IntegerType` | All SQS numeric attrs are strings |
| `SequenceNumber` | string (large integer) | `str` | `StringType` | Too large for int64; keep as string |
| `SenderId` | string | `str` | `StringType` | |
| `CreatedTimestamp` | string (epoch seconds) | `int` → `datetime` | `TimestampType` | Note: seconds (not ms) for queue attrs |
| `LastModifiedTimestamp` | string (epoch seconds) | `int` → `datetime` | `TimestampType` | Note: seconds (not ms) for queue attrs |
| `ApproximateNumberOfMessages` | string (integer) | `int` | `LongType` | Approximate; eventual consistency |
| `VisibilityTimeout` | string (integer) | `int` | `IntegerType` | |
| `MaximumMessageSize` | string (integer) | `int` | `IntegerType` | |
| `MessageRetentionPeriod` | string (integer) | `int` | `IntegerType` | |
| `FifoQueue` | string (`"true"`/`"false"`) | `bool` | `BooleanType` | Parse string to bool |
| `SqsManagedSseEnabled` | string (`"true"`/`"false"`) | `bool` | `BooleanType` | |
| `Policy` | string (JSON) | `str` | `StringType` | Store as raw JSON string |
| `RedrivePolicy` | string (JSON) | `str` | `StringType` | Store as raw JSON string |
| `MessageAttributes` | map | `dict` | `MapType(StringType, StringType)` | Serialize to JSON or flatten |
| `MessageAttribute.StringValue` | string | `str` | `StringType` | |
| `MessageAttribute.BinaryValue` | bytes | `bytes` | `BinaryType` | |
| `MessageAttribute.DataType` | string | `str` | `StringType` | `String`, `Number`, `Binary` (+ optional suffix) |

**Critical type conversion notes:**

1. **All SQS queue attribute values are returned as strings**, even numeric ones. Cast explicitly (e.g., `int(attrs['VisibilityTimeout'])`).
2. **Message timestamps** (`SentTimestamp`, `ApproximateFirstReceiveTimestamp`) are epoch **milliseconds** as strings. Divide by 1000 to get epoch seconds for `datetime.fromtimestamp()`.
3. **Queue timestamps** (`CreatedTimestamp`, `LastModifiedTimestamp`) are epoch **seconds** as strings.
4. **`SequenceNumber`** is a large integer string that exceeds int64 — store as string.
5. **`MessageAttributes`** is a nested dict with `StringValue`, `BinaryValue`, and `DataType`. Serialize to JSON or flatten when writing to Delta.

---

## Known Quirks and Implementation Notes

1. **No timestamp-based filtering on ReceiveMessage:** SQS does not allow filtering messages by send timestamp or any other field. The connector receives whatever is at the head of the queue. This makes true incremental sync (by time range) impossible without external state tracking.

2. **Non-destructive reads require careful VisibilityTimeout management:** If the connector does not delete messages, they reappear after `VisibilityTimeout` seconds. Setting a very long visibility timeout (e.g., 12 hours) during a sync prevents re-reads within a batch but ties up the in-flight quota.

3. **Duplicate `MessageId` across receive calls:** The same message can be returned by multiple `ReceiveMessage` calls if the visibility timeout expires. Downstream deduplication by `MessageId` is essential.

4. **ApproximateNumberOfMessages is approximate:** This field achieves consistency only ~1 minute after producers stop sending. Do not use it for exact message counts.

5. **ListQueues requires MaxResults to paginate:** If `MaxResults` is omitted, the API returns up to 1000 results but will NOT return `NextToken` even if there are more queues. Always set `MaxResults` when paginating.

6. **Cross-account ListQueues not supported:** `ListQueues` only lists queues in the current account. Cross-account queue access requires knowing the queue URL directly.

7. **FIFO queues:** Queue URLs end with `.fifo`. FIFO queues have additional attributes (`SequenceNumber`, `MessageGroupId`, `MessageDeduplicationId`) and stricter throughput limits (300 API calls/sec without batching).

8. **Message body encoding:** SQS does not URL-encode the message body in boto3 responses (it did in older SDK versions). The body is returned as-is.

9. **Extended payloads via S3:** Messages larger than 256 KB use the SQS Extended Client Library with the actual payload stored in S3. The `Body` field in such cases contains a pointer JSON; actual content must be fetched from S3. This connector does not support extended payloads.

10. **KMS-encrypted queues:** If the queue uses KMS encryption, the IAM user needs `kms:Decrypt` permission in addition to SQS permissions.

---

## Research Log

| Source Type | URL | Accessed (UTC) | Confidence | What it confirmed |
|-------------|-----|----------------|------------|-------------------|
| Official Docs | [ReceiveMessage API Reference](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ReceiveMessage.html) | 2026-03-04 | High | All request params, response structure, system attributes, error codes, visibility timeout behavior |
| Official Docs | [ListQueues API Reference](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ListQueues.html) | 2026-03-04 | High | Pagination with NextToken, MaxResults requirement, response structure |
| Official Docs | [GetQueueAttributes API Reference](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_GetQueueAttributes.html) | 2026-03-04 | High | All available attribute names, response structure, error codes |
| Official Docs | [SQS Message Quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html) | 2026-03-04 | High | Message size (1 byte–1 MiB), retention (60s–14d), batch limit (10), in-flight limits |
| Official Docs | [SQS Standard Queue Quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-queues.html) | 2026-03-04 | High | In-flight limit (120k standard, 20k FIFO), ListQueues max 1000, long poll max 20s |
| Official Docs | [SQS API Permissions Reference](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-api-permissions-reference.html) | 2026-03-04 | High | IAM action names, required resource ARN patterns for each action |
| boto3 Reference | [boto3 receive_message](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/receive_message.html) | 2026-03-04 | High | Python SDK params, return types, MessageSystemAttributeNames enum values |
| boto3 Reference | [boto3 list_queues](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/list_queues.html) | 2026-03-04 | High | Python SDK params, pagination pattern, return structure |
| AWS Docs | [SQS FIFO Throttling](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/troubleshooting-fifo-throttling-issues.html) | 2026-03-04 | High | FIFO queue limits: 300 TPS without batching, 3000 TPS with batching |
| AWS Features | [Amazon SQS Features](https://aws.amazon.com/sqs/features/) | 2026-03-04 | High | Standard queues: nearly unlimited TPS confirmed |

---

## Assumptions

1. **Non-destructive reads:** The connector reads messages without deleting them. This is appropriate for a data ingestion connector that should not interfere with the application's message processing.

2. **Single region:** Each connector configuration targets a single AWS region. Multi-region support would require separate connector instances.

3. **Standard queue focus:** Primary documentation targets standard SQS queues. FIFO queue specifics are documented where they differ but are secondary.

4. **No Extended Client Library support:** Messages using the SQS Extended Client Library (payloads in S3) are not supported in this initial implementation. The `Body` field will contain the S3 pointer JSON in such cases.

5. **`MessageAttributes` stored as JSON map:** Custom message attributes are serialized to a JSON string when written to Delta, rather than being flattened into individual columns (since attribute names are producer-defined and vary).
