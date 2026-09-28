"""Fabricated source claims only. Private fixture rules are never installed provider rules."""

import hashlib
import importlib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_bot.config import load_config
from trading_bot.market_data.recording import canonical_json

ROOT = Path(__file__).resolve().parents[3]
START = 1704153600000000000
END = 1704240000000000000
PUBLISHED = START - 1
AS_OF = START + 1
OBSERVED = datetime(2026, 9, 27, tzinfo=UTC)
DOCUMENT = b"Fabricated historical source protocol v1. Not exchange or provider documentation."


def module(name):
    try:
        return importlib.import_module("trading_bot.market_data.options_source_" + name)
    except ModuleNotFoundError:
        pytest.fail("scoped source verification is not implemented")


def config():
    return load_config(
        ROOT / "configs/base.yaml",
        ROOT / "configs/options/native-data/simulation.yaml",
        ROOT / "configs/safety-envelope.yaml",
        {},
    )


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def private_file(directory, name, body):
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / name
    path.write_bytes(body)
    path.chmod(0o600)
    return module("models").PrivateArtifactRef(path, hashlib.sha256(body).hexdigest(), len(body))


def arrangement(
    tmp_path, *, role="bar_publication", published=PUBLISHED, future=False, invalidation=False
):
    models = module("models")
    rules_api = module("rules")
    source_id = "synthetic.source"
    schema = "synthetic-source-records-v1"
    payload = {"kind": role, "identity": "fabricated", "value": "100"}
    record = {
        "published_at_ns": published,
        "effective_start_ns": START,
        "effective_end_ns": END,
        "record": payload,
    }
    records = [record]
    if future:
        records.append(
            {**record, "published_at_ns": AS_OF + 1, "record": {**payload, "identity": "future"}}
        )
    manifest = {
        "schema": schema,
        "source_id": source_id,
        "role": role,
        "era_start_ns": START - 1000,
        "era_end_ns": END + 1000,
        "records": records,
    }
    if invalidation:
        manifest["invalidations"] = [
            {
                "affected_hash": digest(payload),
                "discovered_at": OBSERVED,
                "reason": "source_invalidated",
            }
        ]
    ref = private_file(tmp_path, "reference.txt", DOCUMENT)
    data = private_file(tmp_path, "records.json", canonical_json(manifest).encode())
    rule = models.SourceRule(
        "fixture.rule",
        role,
        source_id,
        schema,
        START - 1000,
        END + 1000,
        (ref.sha256,),
        "synthetic-records-v1",
    )
    coverage = digest(
        {"role": role, "start_ns": START, "end_ns": END, "record_hashes": [digest(record)]}
    )
    claim = models.SourceClaim(
        role,
        source_id,
        schema,
        START - 1000,
        END + 1000,
        (data.sha256,),
        OBSERVED,
        published,
        START,
        END,
        coverage,
        rule.rule_id,
    )
    bundle = models.SourceEvidenceBundle((claim,), (ref,), (data,))
    context = models.VerificationContext(
        AS_OF,
        START,
        END,
        config().config_hash,
        rules_api.source_code_hash(),
        digest([asdict(rule)]),
    )
    return bundle, context, (rule,)


def verify_fixture_bundle(bundle, context, rules):
    return module("verify")._verify_with_rules(
        bundle, context=context, loaded=config(), repository_root=ROOT, rules=rules
    )
