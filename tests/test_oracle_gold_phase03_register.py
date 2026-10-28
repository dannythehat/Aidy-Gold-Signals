"""Committed phase03 receipts, non-equivalence witnesses and CI loss retention."""
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/"reports/gold_oracle/phase03"


def read(path):
    return json.loads(path.read_text())


def test_obtainable_sources_have_five_actual_rule_dimensions_and_individual_gates():
    audit = read(OUT/"remaining50_source_audit.json")
    cs = audit["cards"]
    assert set(cs) == {f"S{i:03}" for i in range(32,82)}
    assert sum(bool(c["source_files"]) for c in cs.values()) == 41
    assert {i for i,c in cs.items() if not c["source_files"]} == {"S056","S057","S072","S073","S074","S075","S076","S077","S078"}
    for card in cs.values():
        assert set(card["rules"]) == {"entry","exit","filters","sizing","management"}
        assert card["blockers"]
        assert card["execution_qualified"] is False
        assert card["native_compilation_or_platform_output_parity"] is False
        for f in card["source_files"]:
            assert len(f["sha256"]) == 64
            assert f["bytes"] > 0 and f["lines"] > 0
            assert all(set(a) == {"line","reviewed_symbol","decoded_line_sha256"} for a in f["review_anchors"])
        if not card["source_files"]:
            assert all(v is None for v in card["rules"].values())


def test_all125_pairs_have_actual_code_evidence_and_no_false_exact_alias():
    old = read(ROOT/"reports/gold_oracle/dedup_mechanics_review.json")["review_flags"]
    new = read(OUT/"125_duplicate_comparisons.json")["comparisons"]
    assert {(r['a'],r['b']) for r in new} == {(r['a'],r['b']) for r in old}
    assert len(new) == 125
    assert sum(r["classification"] == "UNRESOLVED_SOURCE_BLOCKED" for r in new) == 7
    assert sum(bool(r["same_tape_executable_counterexamples"]) for r in new) == 76
    for r in new:
        assert r["complete_fingerprint_equality_proven"] is False
        assert r["all_original_ids_retained"] is True
        assert set(r["five_dimension_review"]) == {"entry","exit","filters","sizing","management"}
        for witness in r["same_tape_executable_counterexamples"]:
            fields = list(witness["geometry"])
            sets = []
            for path, digest in zip(witness["ledger_paths"],witness["ledger_sha256"],strict=True):
                raw = (ROOT/path).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == digest
                sets.append({tuple(v[k] for k in fields) for v in csv.DictReader(io.StringIO(raw.decode()))})
            value = tuple(witness["geometry"][k] for k in fields)
            assert value in sets[0] ^ sets[1]


def test_native_account_ci_artifact_is_exact_complete_and_retains_every_loss():
    register = read(OUT/"account_results_register.json")
    raw = (ROOT/register["committed_artifact"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == register["artifact_zip_sha256"]
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        assert len(z.namelist()) == 26
        assert all(n.endswith(("_trades.csv","_monthly.csv","report.json","tests/junit.xml")) for n in z.namelist())
        for n, digest in register["member_sha256"].items():
            assert hashlib.sha256(z.read(n)).hexdigest() == digest
        report = json.loads(z.read(next(n for n in z.namelist() if n.endswith("report.json"))))
    assert len(register["models"]) == 12
    assert register["negative_cases"] == 8
    for k,m in register["models"].items():
        original = report["models"][k]
        assert m["net_marked_excluding_unverified_funding_usd"] == original["net_marked_excluding_unverified_funding_usd"]
        assert sum(y["net_marked_excluding_funding_usd"] for y in m["years"]) == pytest.approx(m["net_marked_excluding_unverified_funding_usd"])
        assert len(m["years"]) == 3
        assert m["native_broker_qualified"] is False and m["funding_verified"] is False
        if k.endswith("common_stress"):
            assert m["net_marked_excluding_unverified_funding_usd"] < 0


def test_every_original_id_retained_without_fabricated_qualification_or_account():
    r = read(OUT/"independent_strategy_register.json")
    assert [x["id"] for x in r["rows"]] == [f"S{i:03}" for i in range(1,84)]
    assert r["all83_backtested"] is False
    assert r["source_obtained_ids"] == 74 and r["new_account_ids"] == 4
    assert sum(len(x["phase03_account_cases"]) for x in r["rows"]) == 12
    assert all(x["score"] is None and not x["live_activation"] and not x["independent_profitable_edge_certified"] for x in r["rows"])
    assert len(read(OUT/"dependence.json")["pairs"]) == 90
