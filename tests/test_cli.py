"""Exercise the actual installed-package entry point, fully offline."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from technical_engine.cli import _load_json, main

ROOT = Path(__file__).resolve().parents[1]


def test_cli_end_to_end_and_idempotent_fixture(tmp_path):
    fixture = tmp_path / "synthetic.json"
    command = [sys.executable, str(ROOT / "scripts/generate_fixture.py"), "--output", str(fixture)]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    original_fixture = fixture.read_bytes()
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    assert fixture.read_bytes() == original_fixture
    invocation = [
        sys.executable,
        "-m",
        "technical_engine",
        "--input",
        str(fixture),
        "--output",
        str(tmp_path / "reports"),
        "--config",
        str(ROOT / "config/default.json"),
        "--run-at",
        "2025-01-02T00:00:00Z",
    ]
    first = subprocess.run(invocation, cwd=ROOT, check=True, capture_output=True, text=True)
    second = subprocess.run(invocation, cwd=ROOT, check=True, capture_output=True, text=True)
    assert first.stdout == second.stdout
    output = Path(first.stdout.strip())
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["input"]["bar_count"] == 280
    assert manifest["input"]["provider"] == "synthetic-fixture"
    with (output / "features.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 280
    assert rows[198]["sma_200"] == ""
    assert rows[199]["sma_200"] != ""
    assert all(value != "" for value in rows[-1].values())
    assert not list(output.parent.glob(".staging-*"))
    assert not (output.parent / ".artifact-write.lock").exists()


def test_fixture_refuses_to_overwrite_different_snapshot(tmp_path):
    fixture = tmp_path / "input.json"
    fixture.write_text("preserve")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_fixture.py"), "--output", str(fixture)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Refusing to overwrite" in result.stderr
    assert fixture.read_text() == "preserve"


def test_cli_help():
    result = subprocess.run(
        [sys.executable, "-m", "technical_engine", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--run-at" in result.stdout
    assert "research-only" in result.stdout


@pytest.mark.parametrize("timestamp", ["2025-01-02", "garbage"])
def test_cli_requires_aware_run_timestamp(timestamp, tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main(["--input", "irrelevant.json", "--output", str(tmp_path), "--run-at", timestamp])
    assert error.value.code == 2
    assert "timezone" in capsys.readouterr().err


def test_cli_reports_invalid_input_without_traceback(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--input",
                str(bad),
                "--output",
                str(tmp_path / "reports"),
                "--run-at",
                "2025-01-02T00:00:00Z",
            ]
        )
    assert error.value.code == 2
    stderr = capsys.readouterr().err
    assert "technical-engine:" in stderr
    assert "Traceback" not in stderr
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_cli_json_parser_rejects_ambiguous_or_nonfinite_inputs(raw):
    with pytest.raises(ValueError):
        _load_json(raw)
