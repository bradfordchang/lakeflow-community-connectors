from pathlib import Path

from databricks.labs.community_connector.sources.sqs_microflex.sqs_microflex import (
    SqsMicroflexLakeflowConnect,
)
from tests.unit.sources import test_suite
from tests.unit.sources.test_suite import LakeflowConnectTester
from tests.unit.sources.test_utils import load_config


def test_sqs_microflex_connector():
    """Test the SQS Microflex connector using the test suite.

    This test connects to real AWS SQS using credentials from dev_config.json.
    Keep sample_records small to avoid excessive API calls and rate limiting.
    """
    config_dir = Path(__file__).parent / "configs"
    config = load_config(config_dir / "dev_config.json")

    # No table-level config needed for this connector.
    table_config = {}

    test_suite.LakeflowConnect = SqsMicroflexLakeflowConnect

    tester = LakeflowConnectTester(config, table_config, sample_records=10)
    report = tester.run_all_tests()
    tester.print_report(report, show_details=True)

    assert report.passed_tests == report.total_tests, (
        f"Test suite had failures: {report.failed_tests} failed, {report.error_tests} errors"
    )
