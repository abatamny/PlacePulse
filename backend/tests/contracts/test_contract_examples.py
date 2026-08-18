from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[3]
CONTRACT_ROOT = ROOT / "contracts" / "v1"


def test_every_declared_contract_example_has_expected_validity() -> None:
    manifest = json.loads(
        (CONTRACT_ROOT / "examples" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest
    for case in manifest:
        schema = json.loads((CONTRACT_ROOT / case["schema"]).read_text(encoding="utf-8"))
        instance = json.loads(
            (CONTRACT_ROOT / "examples" / case["example"]).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(instance))
        assert bool(errors) is (not case["valid"]), case
