"""
Auth verification test for the sqs_microflex connector.

Reads credentials from dev_config.json, creates a boto3 SQS client,
and calls ListQueues to verify the credentials are valid.
"""

import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def load_config() -> dict:
    config_path = Path(__file__).parent / "configs" / "dev_config.json"
    with open(config_path) as f:
        return json.load(f)


def make_sqs_client(config: dict):
    client_kwargs = {
        "service_name": "sqs",
        "region_name": config["aws_region"],
        "aws_access_key_id": config["aws_access_key_id"],
        "aws_secret_access_key": config["aws_secret_access_key"],
    }
    session_token = config.get("aws_session_token")
    if session_token:
        client_kwargs["aws_session_token"] = session_token
    return boto3.client(**client_kwargs)


def verify_auth(client) -> list[str]:
    """Call ListQueues and return the list of queue URLs found."""
    response = client.list_queues(MaxResults=100)
    return response.get("QueueUrls", [])


def main():
    print("sqs_microflex connector — auth verification test")
    print("-" * 50)

    # Step 1: Load credentials
    print("Step 1: Loading credentials from dev_config.json ... ", end="")
    try:
        config = load_config()
    except FileNotFoundError as exc:
        print("FAIL")
        print(f"  Error: {exc}")
        sys.exit(1)

    required_keys = ["aws_access_key_id", "aws_secret_access_key", "aws_region"]
    missing = [k for k in required_keys if not config.get(k)]
    if missing:
        print("FAIL")
        print(f"  Missing required keys: {missing}")
        sys.exit(1)
    print("OK")

    print(f"  Region : {config['aws_region']}")
    print(f"  Key ID : {config['aws_access_key_id']}")
    has_token = bool(config.get("aws_session_token"))
    print(f"  Session token: {'present' if has_token else 'not present'}")

    # Step 2: Create boto3 SQS client
    print("Step 2: Creating boto3 SQS client ... ", end="")
    try:
        client = make_sqs_client(config)
    except Exception as exc:
        print("FAIL")
        print(f"  Error: {exc}")
        sys.exit(1)
    print("OK")

    # Step 3: Call ListQueues
    print("Step 3: Calling SQS ListQueues ... ", end="")
    try:
        queue_urls = verify_auth(client)
    except NoCredentialsError as exc:
        print("FAIL")
        print(f"  No credentials: {exc}")
        sys.exit(1)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        message = exc.response["Error"]["Message"]
        print("FAIL")
        print(f"  AWS error [{code}]: {message}")
        sys.exit(1)
    except Exception as exc:
        print("FAIL")
        print(f"  Unexpected error: {exc}")
        sys.exit(1)
    print("OK")

    # Step 4: Report results
    print("-" * 50)
    print("AUTH VERIFICATION: SUCCESS")
    print(f"  Queues found in {config['aws_region']}: {len(queue_urls)}")
    for url in queue_urls:
        print(f"    - {url}")
    if not queue_urls:
        print("  (No queues found — credentials are valid but the account/region has no queues)")


if __name__ == "__main__":
    main()
