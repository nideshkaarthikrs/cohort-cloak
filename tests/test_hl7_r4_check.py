"""The external validator must fail on issues even when Java exits zero."""
import io
import tarfile
from pathlib import Path
import pytest
from tools import hl7_r4_check as check


def issue(severity="error", diagnostic="Missing required category"):
    return {"severity": severity, "code": "invalid", "diagnostics": diagnostic,
            "expression": ["Bundle.entry[0].resource"]}


def test_errors_are_not_success_even_if_process_returned_zero():
    result, code = check.assess_issues([issue()])
    assert code == 1 and result["error_count"] == 1
    assert not result["passes_requested_checks"]
    assert result["absolute_conformance"] is False


def test_unchanged_source_errors_are_visible_in_comparison():
    result, code = check.assess_issues([issue()], [issue()])
    assert code == 0 and result["comparison"]["pre_existing_error_count"] == 1
    assert result["error_count"] == 1 and not result["passes_requested_checks"]
    assert not result["absolute_conformance"]


def test_new_error_and_duplicate_error_fail_regression():
    for current in ([issue(), issue()], [issue(diagnostic="Broken reference")]):
        result, code = check.assess_issues(current, [issue()])
        assert code == 1 and result["comparison"]["introduced_error_count"] == 1


def test_warnings_do_not_claim_complete_certification():
    result, code = check.assess_issues([issue("warning")])
    assert code == 0 and result["passes_requested_checks"]
    assert not result["absolute_conformance"]


def test_bundle_outcomes_are_read_in_full():
    bundle = {"resourceType": "Bundle", "entry": [{"resource": {
        "resourceType": "OperationOutcome", "issue": [issue()]}}, {"resource": {
        "resourceType": "OperationOutcome", "issue": [issue("fatal")]}}]}
    result, code = check.assess_issues(check.outcome_issues(bundle))
    assert code == 1 and result["error_count"] == 2


def test_empty_and_non_outcomes_fail_closed():
    for value in ({}, {"resourceType": "Bundle", "entry": []},
                  {"resourceType": "OperationOutcome", "issue": []},
                  {"resourceType": "OperationOutcome", "issue": [{"severity": "unknown"}]}):
        with pytest.raises(check.CheckFailure):
            check.outcome_issues(value)


def test_paths_and_cache_volume_cannot_escape(tmp_path):
    with pytest.raises(check.CheckFailure):
        check.separated_paths(tmp_path / "input", tmp_path / "input/out", tmp_path / "tools")
    for value in ("/host/path", "../cache", "--privileged", "cache,option"):
        with pytest.raises(check.CheckFailure):
            check.validate_cache_volume(value)


def test_validation_container_is_offline_and_pinned():
    command = check.container_command("test-check", [], "java", ["-version"])
    assert command[command.index("--network") + 1] == "none"
    assert "--pull=never" in command and "--read-only" in command
    assert check.IMAGE in command and "@sha256:" in check.IMAGE


def test_archive_traversal_is_rejected_before_extraction(tmp_path):
    path = tmp_path / "bad.tgz"
    with tarfile.open(path, "w:gz") as archive:
        item = tarfile.TarInfo("package/../../escaped")
        item.size = 4
        archive.addfile(item, io.BytesIO(b"data"))
    with pytest.raises(check.CheckFailure):
        check.verified_archive(path, check.PACKAGES[0], tmp_path / "stage")
    assert not (tmp_path / "escaped").exists()
