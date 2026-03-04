# Lakeflow SQS Microflex Community Connector

This documentation describes how to configure and use the **SQS Microflex** Lakeflow community connector to ingest data from AWS SQS (Simple Queue Service) into Databricks.


## Prerequisites

- **AWS account**: You need an AWS account with access to the SQS queues you want to read.
- **IAM credentials**:
  - An IAM user or role with an access key ID and secret access key.
  - The IAM principal must have permissions for `sqs:ListQueues`, `sqs:GetQueueAttributes`, and `sqs:ReceiveMessage` on the target queues.
  - If queues use KMS encryption, the IAM principal also needs `kms:Decrypt` permission.
- **Network access**: The environment running the connector must be able to reach the SQS endpoint for your region (e.g., `https://sqs.us-east-1.amazonaws.com`).
- **Lakeflow / Databricks environment**: A workspace where you can register a Lakeflow community connector and run ingestion pipelines.

## Setup

### Required Connection Parameters

Provide the following **connection-level** options when configuring the connector:

| Name | Type | Required | Description | Example |
|------|------|----------|-------------|---------|
| `aws_access_key_id` | string | yes | IAM user access key ID. | `AKIA...` |
| `aws_secret_access_key` | string | yes | IAM user secret access key. | *(your secret key)* |
| `aws_region` | string | yes | AWS region where the SQS queues reside. | `us-east-1` |
| `aws_session_token` | string | no | Temporary session token, required when using STS assumed-role credentials. | `AQoDYXdzEJr...` |

This connector does not require table-specific options, so `externalOptionsAllowList` does not need to be included as a connection parameter.

### Obtaining the Required Parameters

1. **IAM Access Key**:
   - Sign in to the AWS Management Console.
   - Navigate to **IAM > Users > [your user] > Security credentials**.
   - Under **Access keys**, click **Create access key**.
   - Copy the access key ID and secret access key. Store them securely.
2. **AWS Region**:
   - Identify the region where your SQS queues are deployed (e.g., `us-east-1`, `eu-west-1`).
3. **Session Token** (optional):
   - If using temporary credentials via AWS STS `AssumeRole`, the session token is returned alongside the temporary access key ID and secret. Pass all three to the connector.

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
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:REGION:ACCOUNT_ID:*"
    }
  ]
}
```

Replace `REGION` and `ACCOUNT_ID` with your values. You can scope the `SQSReadMessages` statement to specific queue ARNs for least-privilege access.

### Create a Unity Catalog Connection

A Unity Catalog connection for this connector can be created in two ways via the UI:

1. Follow the **Lakeflow Community Connector** UI flow from the **Add Data** page.
2. Select any existing Lakeflow Community Connector connection for this source or create a new one.
3. Provide the required connection parameters (`aws_access_key_id`, `aws_secret_access_key`, `aws_region`).

The connection can also be created using the standard Unity Catalog API.


## Supported Objects

The SQS Microflex connector exposes a **static list** of two tables:

- `queues`
- `messages`

### Object summary, primary keys, and ingestion mode

| Table | Description | Ingestion Type | Primary Key | Incremental Cursor |
|-------|-------------|----------------|-------------|-------------------|
| `queues` | Metadata and attributes for all SQS queues in the configured account and region. Each row represents one queue with its configuration and approximate message counts. | `snapshot` | `queue_url` | n/a |
| `messages` | Messages received from all SQS queues. Messages are read non-destructively (not deleted after reading) and deduplicated by `message_id`. | `append` | `message_id` | `sent_timestamp` |

### Table: `queues`

A full-refresh snapshot of all SQS queues. On each sync, the connector calls `ListQueues` to discover all queue URLs, then calls `GetQueueAttributes` for each queue to retrieve its configuration and statistics.

Key columns include:

| Column | Type | Description |
|--------|------|-------------|
| `queue_url` | string | Full URL of the queue (primary key). |
| `queue_name` | string | Queue name derived from the URL. |
| `queue_arn` | string | Amazon Resource Name of the queue. |
| `approximate_number_of_messages` | long | Approximate count of visible messages. |
| `approximate_number_of_messages_not_visible` | long | In-flight messages (received but not deleted). |
| `created_timestamp` | timestamp | Queue creation time. |
| `last_modified_timestamp` | timestamp | Last modification time. |
| `visibility_timeout` | long | Default visibility timeout in seconds. |
| `fifo_queue` | boolean | Whether this is a FIFO queue. |
| `sqs_managed_sse_enabled` | boolean | Whether SSE-SQS encryption is enabled. |
| `redrive_policy` | string | Dead-letter queue configuration (JSON). |

Additional columns are available for message size limits, retention periods, delay settings, KMS encryption details, FIFO-specific settings, and queue access policies. See the full schema in `sqs_microflex_schemas.py`.

### Table: `messages`

An append-only stream of messages received from all queues. The connector discovers all queues via `ListQueues`, then polls each queue using `ReceiveMessage` until no more messages are returned. Messages are **not deleted** after reading (non-destructive read pattern).

Key columns include:

| Column | Type | Description |
|--------|------|-------------|
| `message_id` | string | Globally unique message identifier (primary key). |
| `queue_url` | string | URL of the queue this message was received from. |
| `body` | string | Raw message body content. |
| `sent_timestamp` | timestamp | Time the message was sent (cursor field). |
| `approximate_receive_count` | long | Number of times this message has been received. |
| `sender_id` | string | IAM user or role ID of the message sender. |
| `receipt_handle` | string | Opaque handle for the receive operation. |
| `message_attributes` | string | Custom message attributes serialized as JSON. |

Additional columns are available for MD5 checksums, FIFO-specific fields (`sequence_number`, `message_group_id`, `message_deduplication_id`), X-Ray trace headers, and dead-letter queue source ARNs. See the full schema in `sqs_microflex_schemas.py`.

## Table Configurations

### Source & Destination

These are set directly under each `table` object in the pipeline spec:

| Option | Required | Description |
|---|---|---|
| `source_table` | Yes | Table name in the source system (`queues` or `messages`). |
| `destination_catalog` | No | Target catalog (defaults to pipeline's default). |
| `destination_schema` | No | Target schema (defaults to pipeline's default). |
| `destination_table` | No | Target table name (defaults to `source_table`). |

### Common `table_configuration` options

These are set inside the `table_configuration` map alongside any source-specific options:

| Option | Required | Description |
|---|---|---|
| `scd_type` | No | `SCD_TYPE_1` (default) or `SCD_TYPE_2`. Only applicable to the `queues` table (snapshot ingestion mode); the `messages` table uses append-only ingestion and does not support this option. |
| `primary_keys` | No | List of columns to override the connector's default primary keys. |
| `sequence_by` | No | Column used to order records for SCD Type 2 change tracking. |

### Source-specific `table_configuration` options

This connector does not require any source-specific table configuration options. All queues in the configured region and account are read automatically.


## Data Type Mapping

AWS SQS returns all attribute values as strings. The connector converts them to appropriate Spark types:

| SQS API Type | Example Fields | Spark Type | Notes |
|---|---|---|---|
| String (URL) | `QueueUrl`, `queue_url` | `StringType` | |
| String (ARN) | `QueueArn`, `queue_arn` | `StringType` | |
| String (UUID) | `MessageId`, `message_id` | `StringType` | |
| String (opaque) | `ReceiptHandle`, `receipt_handle` | `StringType` | Can be very long. |
| String (message body) | `Body`, `body` | `StringType` | May contain JSON; parse downstream. |
| String (JSON policy) | `Policy`, `RedrivePolicy` | `StringType` | Stored as raw JSON strings. |
| String (numeric) | `ApproximateNumberOfMessages`, `VisibilityTimeout` | `LongType` | Cast from string to integer. |
| String (epoch seconds) | `CreatedTimestamp`, `LastModifiedTimestamp` | `TimestampType` | Queue timestamps are epoch seconds. |
| String (epoch milliseconds) | `SentTimestamp`, `ApproximateFirstReceiveTimestamp` | `TimestampType` | Message timestamps are epoch milliseconds, divided by 1000. |
| String (`"true"`/`"false"`) | `FifoQueue`, `SqsManagedSseEnabled` | `BooleanType` | Parsed from string to boolean. |
| String (large integer) | `SequenceNumber` | `StringType` | Exceeds int64 range; kept as string. |
| Nested map | `MessageAttributes` | `StringType` | Serialized to JSON string for storage. |


## How to Run

### Step 1: Clone/Copy the Source Connector Code

Follow the Lakeflow Community Connector UI, which will guide you through setting up a pipeline using the selected source connector code.

### Step 2: Configure Your Pipeline

Update the `pipeline_spec` in the main pipeline file (e.g., `ingest.py`). Because this connector has no table-specific options, the configuration is straightforward:

```json
{
  "pipeline_spec": {
    "connection_name": "sqs_microflex_connection",
    "object": [
      {
        "table": {
          "source_table": "queues"
        }
      },
      {
        "table": {
          "source_table": "messages"
        }
      }
    ]
  }
}
```

- `connection_name` must point to the Unity Catalog connection configured with your AWS credentials (`aws_access_key_id`, `aws_secret_access_key`, `aws_region`).
- For each `table`, `source_table` must be either `queues` or `messages`.

### Step 3: Run and Schedule the Pipeline

Run the pipeline using your standard Lakeflow / Databricks orchestration (e.g., a scheduled job or workflow).

- The `queues` table performs a full snapshot on each run, replacing all queue metadata with current values.
- The `messages` table appends newly received messages on each run. The connector tracks previously seen message IDs to avoid duplicates across runs.

#### Best Practices

- **Start small**: Begin by syncing the `queues` table alone to validate that credentials and network access are configured correctly.
- **Schedule appropriately**: SQS messages have a retention period (default 4 days, max 14 days). Schedule the pipeline frequently enough to capture messages before they expire and are removed from the queue.
- **Non-destructive reads**: This connector does not delete messages. Messages become invisible for the `VisibilityTimeout` period (30 seconds) after being read, then return to the queue. This does not interfere with other consumers, but be aware that the same messages may be re-read on subsequent runs (the connector deduplicates by `message_id`).
- **Monitor in-flight limits**: Standard SQS queues support up to 120,000 in-flight messages (20,000 for FIFO). Large-scale polling may approach these limits.
- **FIFO queues**: FIFO queues (URLs ending in `.fifo`) have stricter throughput limits of 300 API calls per second without batching. The connector handles them automatically but ingestion may be slower.

#### Troubleshooting

Common issues and how to address them:

- **Authentication failures (`InvalidClientTokenId`, `SignatureDoesNotMatch`)**:
  - Verify that `aws_access_key_id` and `aws_secret_access_key` are correct and not expired.
  - If using temporary credentials, confirm that `aws_session_token` is provided and still valid.
- **Access denied (`AccessDenied`)**:
  - Ensure the IAM policy grants `sqs:ListQueues`, `sqs:GetQueueAttributes`, and `sqs:ReceiveMessage` for the target queues and region.
  - For KMS-encrypted queues, verify that the IAM principal has `kms:Decrypt` permission.
- **No queues returned**:
  - Confirm that `aws_region` matches the region where your queues are deployed. `ListQueues` only returns queues in the specified region.
  - Cross-account queues are not discovered by `ListQueues`; they must be accessed by direct URL.
- **No messages returned**:
  - SQS standard queues use short polling by default, which may return empty responses even when messages exist. The connector uses long polling (1-second wait) to reduce this.
  - Messages may be invisible due to a prior `ReceiveMessage` call (by this connector or another consumer). They will reappear after the visibility timeout expires.
- **Throttling (`RequestThrottled`, `OverLimit`)**:
  - The connector implements exponential backoff with up to 5 retries. If throttling persists, reduce the pipeline's execution frequency or contact AWS support to increase limits.
- **Duplicate messages in the `messages` table**:
  - SQS standard queues may deliver messages more than once. The connector deduplicates within a single run using `message_id`, but duplicates can occur across separate runs if the offset state is reset. Use downstream deduplication on `message_id` if exact-once semantics are required.


## References

- Connector implementation: `src/databricks/labs/community_connector/sources/sqs_microflex/sqs_microflex.py`
- Connector schemas: `src/databricks/labs/community_connector/sources/sqs_microflex/sqs_microflex_schemas.py`
- Connector API documentation: `src/databricks/labs/community_connector/sources/sqs_microflex/sqs_microflex_api_doc.md`
- Official AWS SQS documentation:
  - https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/welcome.html
  - https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ReceiveMessage.html
  - https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_ListQueues.html
  - https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_GetQueueAttributes.html
  - https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-api-permissions-reference.html
