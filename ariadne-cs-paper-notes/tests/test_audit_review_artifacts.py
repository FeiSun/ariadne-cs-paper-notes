#!/usr/bin/env python3
"""Regression tests for structured Ariadne review artifact auditing."""

from __future__ import annotations

import importlib.util
import copy
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_review_artifacts.py"
FIXTURES = ROOT / "tests" / "fixtures"
ARTIFACTS = FIXTURES / "review_artifacts"
HTML = FIXTURES / "expected_html_report.html"
SOURCE = FIXTURES / "source_paper_reader.html"


def load_module():
    spec = importlib.util.spec_from_file_location("audit_review_artifacts", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load audit_review_artifacts module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(payload: object) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    with tmp:
        json.dump(payload, tmp)
    return Path(tmp.name)


def only_legacy_issue_artifact_warning(warnings: list[str]) -> bool:
    return warnings == ["legacy bundle: issue_artifacts/ absent; recommend migration"]


def load_manifest(**paper_reader_overrides: object) -> dict[str, object]:
    payload = json.loads((ARTIFACTS / "render_manifest.json").read_text(encoding="utf-8"))
    paper_reader = copy.deepcopy(payload["paper_reader"])
    paper_reader.update(paper_reader_overrides)
    payload["paper_reader"] = paper_reader
    return payload


def valid_finding(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "F1",
        "severity": "Blocker",
        "location": "Abstract",
        "domain": "layout",
        "diagnosis": "摘要缺少问题、缺口、核心想法和证据边界。",
        "reader_friction": "读者无法从第一页恢复这篇论文想让自己相信什么。",
        "writing_principle": "低认知负担 / reader-first",
        "self_check": "下一稿能否让读者只看摘要就说出问题、缺口、想法、证据和边界？",
        "next_draft_task": "补齐 problem/gap/idea/evidence/boundary。",
        "evidence_basis": "rendered PDF",
        "verification_method": "PDF visual pass",
        "confidence": "high",
        "severity_rationale": "第一页无法恢复主线会直接影响审稿人是否继续相信后文。",
        "downgrade_condition": "摘要补齐主线闭环后可降级。",
    }
    payload.update(overrides)
    return payload


def test_review_artifact_fixture_passes_contract() -> None:
    module = load_module()
    errors, warnings = module.audit_artifacts(
        ARTIFACTS / "findings.json",
        ARTIFACTS / "claims.json",
        ARTIFACTS / "numeric_audit.json",
        ARTIFACTS / "coverage.json",
        ARTIFACTS / "render_manifest.json",
        ARTIFACTS / "pass_observations.json",
        HTML,
        SOURCE,
        ARTIFACTS / "annotations.json",
        ARTIFACTS,
        ARTIFACTS / "layout_audit.json",
    )
    if errors or not only_legacy_issue_artifact_warning(warnings):
        raise AssertionError(f"Structured artifact audit failed.\nErrors: {errors}\nWarnings: {warnings}")


def test_bundle_cli_paths_pass_contract() -> None:
    module = load_module()
    errors, warnings = module.audit_artifacts(
        ARTIFACTS / "findings.json",
        ARTIFACTS / "claims.json",
        ARTIFACTS / "numeric_audit.json",
        ARTIFACTS / "coverage.json",
        ARTIFACTS / "render_manifest.json",
        ARTIFACTS / "pass_observations.json",
        HTML,
        SOURCE,
        ARTIFACTS / "annotations.json",
        ARTIFACTS,
        ARTIFACTS / "layout_audit.json",
    )
    if errors or not only_legacy_issue_artifact_warning(warnings):
        raise AssertionError(f"Bundle-equivalent artifact audit failed.\nErrors: {errors}\nWarnings: {warnings}")


def test_high_risk_finding_requires_downgrade_condition() -> None:
    module = load_module()
    finding = valid_finding()
    del finding["downgrade_condition"]
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("downgrade_condition" in error for error in errors):
        raise AssertionError(f"Expected downgrade_condition error, got {errors}")


def test_visible_prose_finding_rejects_english_or_fallback_contract() -> None:
    module = load_module()
    finding = valid_finding(
        domain="prose",
        diagnosis="The opening overclaims without an evidence boundary.",
        reader_friction="The reader cannot recover the boundary.",
        writing_principle="reader-first prose",
        self_check="Can the next draft clarify the boundary?",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("Chinese" in error or "closed Ariadne principle" in error for error in errors):
        raise AssertionError(f"Expected visible Prose language/principle errors, got {errors}")

    fallback = valid_finding(domain="whole_paper", compiler_fallback_fields=["reader_friction"])
    path = write_json({"findings": [fallback]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("compiler fallback" in error for error in errors):
        raise AssertionError(f"Expected compiler fallback error, got {errors}")

    issue_type_fallback = valid_finding(domain="", issue_type="prose", compiler_fallback_fields=["self_check"])
    path = write_json({"findings": [issue_type_fallback]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("compiler fallback" in error for error in errors):
        raise AssertionError(f"Expected issue_type-only compiler fallback error, got {errors}")


def test_json_finding_must_render_or_be_deferred() -> None:
    module = load_module()
    path = write_json({"findings": [valid_finding(id="F99")]})
    try:
        errors, _ = module.audit_artifacts(path, html_path=HTML)
    finally:
        path.unlink(missing_ok=True)
    if not any("not rendered in HTML" in error for error in errors):
        raise AssertionError(f"Expected render/deferred error, got {errors}")


def test_artifact_only_json_finding_may_be_absent_from_html() -> None:
    module = load_module()
    path = write_json({"findings": [valid_finding(id="F99", render_visibility="artifact_only")]})
    try:
        errors, _ = module.audit_artifacts(path, html_path=HTML)
    finally:
        path.unlink(missing_ok=True)
    if any("not rendered in HTML" in error for error in errors):
        raise AssertionError(f"Artifact-only finding should be treated as deferred for HTML rendering: {errors}")


def test_skipped_coverage_requires_pending_marker() -> None:
    module = load_module()
    path = write_json({"units": [{"unit": "Pages", "total": 10, "reviewed": 8, "with_issues": 2, "clean": 6, "skipped": 2}]})
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", coverage_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("skipped > 0 without pending_in" in error for error in errors):
        raise AssertionError(f"Expected skipped coverage error, got {errors}")


def test_layout_sampled_pages_cannot_claim_full_coverage() -> None:
    module = load_module()
    path = write_json(
        {
            "units": [{"unit": "Pages", "total": 30, "reviewed": 5, "with_issues": 2, "clean": 3, "skipped": 25, "pending_in": "layout subpass"}],
            "layout": {
                "pages_total": 30,
                "pages_checked": 5,
                "pages_sampled": [1, 2, 5, 10, 24],
                "pages_escalated": [5],
                "full_layout_coverage": True,
            },
            "reader_journey_passes": [{"pass": f"Pass {idx}", "status": "done"} for idx in range(7)],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", coverage_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("full_layout_coverage" in error and "pages_checked" in error for error in errors):
        raise AssertionError(f"Expected sampled/full layout coverage error, got {errors}")


def test_layout_coverage_requires_layout_audit() -> None:
    module = load_module()
    path = write_json(
        {
            "units": [{"unit": "Pages", "total": 3, "reviewed": 3, "with_issues": 1, "clean": 2, "skipped": 0}],
            "layout": {
                "pages_total": 3,
                "pages_checked": 3,
                "pages_sampled": [],
                "pages_escalated": [2],
                "full_layout_coverage": True,
            },
            "reader_journey_passes": [{"pass": f"Pass {idx}", "status": "done"} for idx in range(7)],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", coverage_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("no layout_audit.json" in error for error in errors):
        raise AssertionError(f"Expected missing layout_audit error, got {errors}")


def test_layout_audit_provenance_is_checked() -> None:
    module = load_module()
    layout_audit = write_json(
        {
            "tool": "scripts/check_page_layout.py",
            "tool_version": "1",
            "script_hash": "sha256:72075ef2e29b876f30d65d72f29a298f6d70032198c7ec6da1c08535b915cacb",
            "pdf": "debug/Hidden_Knowledge_with_RL/main.pdf",
            "pdf_hash": "sha256:1111111111111111",
            "pages_total": 2,
            "pages_checked": [1, 2],
            "observations": [
                {
                    "observation_id": "layout-p001-001",
                    "page": 1,
                    "issue_type": "isolated_word_line",
                    "severity": "polish",
                    "observation": "Single word line.",
                    "evidence": "Line text: `Result`.",
                    "needs_main_review": False,
                    "produced_by": "manual",
                    "script_hash": "sha256:72075ef2e29b876f30d65d72f29a298f6d70032198c7ec6da1c08535b915cacb",
                }
            ],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", layout_audit_path=layout_audit)
    finally:
        layout_audit.unlink(missing_ok=True)
    if not any("produced_by" in error for error in errors):
        raise AssertionError(f"Expected produced_by provenance error, got {errors}")


def test_layout_audit_pdf_hash_is_recomputed_when_pdf_exists() -> None:
    module = load_module()
    with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as pdf_handle:
        pdf_handle.write(b"%PDF-1.4\nfixture bytes\n%%EOF\n")
        pdf_path = Path(pdf_handle.name)
    layout_audit = write_json(
        {
            "tool": "scripts/check_page_layout.py",
            "tool_version": "1",
            "script_hash": module.sha256_path(ROOT / "scripts" / "check_page_layout.py"),
            "pdf": str(pdf_path),
            "pdf_hash": "sha256:0000000000000000",
            "pages_total": 1,
            "pages_checked": [1],
            "observations": [],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", layout_audit_path=layout_audit)
    finally:
        pdf_path.unlink(missing_ok=True)
        layout_audit.unlink(missing_ok=True)
    if not any("pdf_hash does not match" in error for error in errors):
        raise AssertionError(f"Expected PDF hash mismatch error, got {errors}")


def test_layout_audit_rejects_missing_pdf_for_replay() -> None:
    module = load_module()
    layout_audit = write_json(
        {
            "tool": "scripts/check_page_layout.py",
            "tool_version": "1",
            "script_hash": module.sha256_path(ROOT / "scripts" / "check_page_layout.py"),
            "pdf": "missing-layout-source.pdf",
            "pdf_hash": "sha256:1111111111111111",
            "pages_total": 1,
            "pages_checked": [1],
            "observations": [],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", layout_audit_path=layout_audit)
    finally:
        layout_audit.unlink(missing_ok=True)
    if not any("referenced PDF does not exist" in error for error in errors):
        raise AssertionError(f"Expected missing PDF replay error, got {errors}")


def test_layout_audit_replay_rejects_tampered_observations() -> None:
    module = load_module()
    payload = json.loads((ARTIFACTS / "layout_audit.json").read_text(encoding="utf-8"))
    payload["pdf"] = str(ROOT / "debug" / "Hidden_Knowledge_with_RL" / "main.pdf")
    payload["observations"][0]["evidence"] = "Line text: `tampered`."
    layout_audit = write_json(payload)
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", layout_audit_path=layout_audit)
    finally:
        layout_audit.unlink(missing_ok=True)
    if not any("fresh scripts/check_page_layout.py run" in error for error in errors):
        raise AssertionError(f"Expected layout replay mismatch error, got {errors}")


def test_layout_finding_requires_layout_audit_provenance() -> None:
    module = load_module()
    finding = valid_finding(
        id="F-layout",
        severity="Polish",
        issue_type="layout",
        location="PDF p.1",
        diagnosis="Single-word line appears in the body area.",
        evidence_basis="PDF layout observation",
        verification_method="manual visual inspection",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path, layout_audit_path=ARTIFACTS / "layout_audit.json")
    finally:
        path.unlink(missing_ok=True)
    expected = ("produced_by", "script_hash", "layout_issue_type")
    if not all(any(fragment in error for error in errors) for fragment in expected):
        raise AssertionError(f"Expected layout finding provenance errors, got {errors}")


def test_layout_finding_accepts_layout_audit_observation_id() -> None:
    module = load_module()
    finding = valid_finding(
        id="F-layout",
        severity="Polish",
        issue_type="layout",
        location="PDF p.1",
        diagnosis="Single-word line appears in the body area.",
        evidence_basis="PDF layout observation",
        verification_method="scripts/check_page_layout.py layout audit",
        produced_by="scripts/check_page_layout.py",
        script_hash="sha256:72075ef2e29b876f30d65d72f29a298f6d70032198c7ec6da1c08535b915cacb",
        page=4,
        layout_audit_observation_id="layout-p004-001",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, warnings = module.audit_artifacts(path, layout_audit_path=ARTIFACTS / "layout_audit.json")
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Layout finding with audit observation id should pass, got errors={errors}, warnings={warnings}")


def test_pass_5_layout_observation_requires_explicit_provenance() -> None:
    module = load_module()
    payload = json.loads((ARTIFACTS / "pass_observations.json").read_text(encoding="utf-8"))
    item = payload["pass_5_submission_walk"][1]
    del item["produced_by"]
    del item["script_hash"]
    path = write_json(payload)
    try:
        errors, _ = module.audit_artifacts(
            ARTIFACTS / "findings.json",
            pass_observations_path=path,
            layout_audit_path=ARTIFACTS / "layout_audit.json",
        )
    finally:
        path.unlink(missing_ok=True)
    expected = ("produced_by", "script_hash")
    if not all(any(fragment in error for error in errors) for fragment in expected):
        raise AssertionError(f"Expected pass observation provenance errors, got {errors}")


def test_forbidden_duplicate_artifacts_are_rejected() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        bundle = root / "bundle"
        bundle.mkdir()
        html = root / "paper.html"
        source = root / "paper.source.html"
        (bundle / "build_overlay_artifacts.py").write_text("ANNOTATIONS = []\n", encoding="utf-8")
        (root / "paper.source_preview.html").write_text("<html></html>\n", encoding="utf-8")
        (root / "main_pdftotext.txt").write_text("duplicate paper text\n", encoding="utf-8")
        html.write_text("<html></html>\n", encoding="utf-8")
        source.write_text("<html></html>\n", encoding="utf-8")
        errors, _ = module.audit_forbidden_artifacts(bundle_path=bundle, html_path=html, source_path=source)
    expected = ("generated helper script", "duplicate paper HTML", "plaintext paper dump")
    if not all(any(fragment in error for error in errors) for fragment in expected):
        raise AssertionError(f"Expected forbidden artifact errors, got {errors}")


def test_full_paper_annotations_must_not_be_top_issue_sample() -> None:
    module = load_module()
    coverage = write_json(
        {
            "requested_scope": "Full main.tex full-paper 逐句 review",
            "units": [
                {"unit": "sentences", "total": 520, "reviewed": 520, "with_issues": 35, "clean": 485, "skipped": 0},
                {"unit": "paragraphs", "total": 421, "reviewed": 421, "with_issues": 8, "clean": 413, "skipped": 0},
                {"unit": "sections/headings", "total": 36, "reviewed": 36, "with_issues": 5, "clean": 31, "skipped": 0},
            ],
            "reader_journey_passes": [
                {"pass": f"Pass {idx}", "status": "done"} for idx in range(7)
            ],
        }
    )
    annotations = write_json(
        {
            "annotations": [
                {
                    "issue_id": f"A{idx}",
                    "target_level": "sentence",
                    "sentence_id": f"s-intro-{idx:03d}",
                    "severity": "major",
                    "issue_type": "claim",
                    "problem": "Sampled sentence issue.",
                    "why": "The reader loses the thread.",
                    "principle": "no sampling",
                    "self_check": "Was this generated from the current sentence?",
                }
                for idx in range(1, 36)
            ]
        }
    )
    try:
        errors, _ = module.audit_artifacts(
            ARTIFACTS / "findings.json",
            coverage_path=coverage,
            annotations_path=annotations,
        )
    finally:
        coverage.unlink(missing_ok=True)
        annotations.unlink(missing_ok=True)
    if not any("top-issue sampling" in error for error in errors):
        raise AssertionError(f"Expected sampled annotation-density error, got {errors}")


def test_full_paper_receipts_allow_sparse_visible_annotations() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir)
        (bundle / "issue_artifacts").mkdir()
        review_units = bundle / "paper.review_units.jsonl"
        review_units.write_text(
            "\n".join(
                json.dumps({"kind": "paragraph", "paragraph_id": f"p{idx}", "section_id": "intro"})
                for idx in range(1, 101)
            )
            + "\n"
            + json.dumps({"kind": "section", "section_id": "intro", "text": "Intro"})
            + "\n",
            encoding="utf-8",
        )
        (bundle / "paragraph_decisions.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {
                        "paragraph_id": f"p{idx}",
                        "section_id": "intro",
                        "decision": "keep",
                        "paragraph_job": "完成局部论证任务。",
                        "next_draft_task": "保持即可。",
                        "all_sentences_reviewed": True,
                    },
                    ensure_ascii=False,
                )
                for idx in range(1, 101)
            )
            + "\n",
            encoding="utf-8",
        )
        (bundle / "section_reflections.json").write_text(
            json.dumps(
                {"sections": [{"section_id": "intro", "one_line": "已深读。", "role_in_argument": "铺垫。", "unresolved_questions": []}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        coverage = write_json(
            {
                "requested_scope": "Full main.tex full-paper 逐句 review",
                "units": [
                    {"unit": "sentences", "total": 520, "reviewed": 520, "with_issues": 1, "clean": 519, "skipped": 0},
                    {"unit": "paragraphs", "total": 100, "reviewed": 100, "with_issues": 0, "clean": 100, "skipped": 0},
                    {"unit": "sections/headings", "total": 1, "reviewed": 1, "with_issues": 0, "clean": 1, "skipped": 0},
                ],
                "reader_journey_passes": [{"pass": f"Pass {idx}", "status": "done"} for idx in range(7)],
            }
        )
        annotations = write_json(
            {
                "annotations": [
                    {
                        "issue_id": "A1",
                        "target_level": "sentence",
                        "sentence_id": "s-intro-001",
                        "severity": "major",
                        "issue_type": "claim",
                        "problem": "有一个可见问题。",
                        "why": "读者会卡住。",
                        "principle": "显式逻辑，不让读者猜",
                        "self_check": "下一稿能否补齐逻辑桥？",
                    }
                ]
            }
        )
        try:
            errors, warnings = module.audit_artifacts(
                ARTIFACTS / "findings.json",
                coverage_path=coverage,
                annotations_path=annotations,
                bundle_path=bundle,
            )
        finally:
            coverage.unlink(missing_ok=True)
            annotations.unlink(missing_ok=True)
    if any("top-issue sampling" in error or "paragraph coverage" in error for error in errors):
        raise AssertionError(f"Complete Phase A receipts should allow sparse visible annotations, got errors={errors}")
    if any("50 or fewer annotations" in warning for warning in warnings):
        raise AssertionError(f"Complete Phase A receipts should suppress sparse annotation warning, got warnings={warnings}")


def test_annotations_must_match_current_source_hash() -> None:
    module = load_module()
    payload = json.loads((ARTIFACTS / "annotations.json").read_text(encoding="utf-8"))
    payload["source_hash"] = "sha256:0000000000000000"
    annotations = write_json(payload)
    try:
        errors, _ = module.audit_artifacts(
            ARTIFACTS / "findings.json",
            manifest_path=ARTIFACTS / "render_manifest.json",
            annotations_path=annotations,
        )
    finally:
        annotations.unlink(missing_ok=True)
    if not any("current manuscript" in error for error in errors):
        raise AssertionError(f"Expected current-source hash mismatch error, got {errors}")


def test_numerical_finding_requires_aggregation_caveat() -> None:
    module = load_module()
    finding = valid_finding(
        id="F2",
        reported_value="95.77",
        visible_computed_value="95.52",
        delta="+0.25",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("aggregation_caveat" in error for error in errors):
        raise AssertionError(f"Expected aggregation_caveat error, got {errors}")


def test_numerical_finding_must_be_blocker() -> None:
    module = load_module()
    finding = valid_finding(
        id="F2",
        severity="Minor",
        diagnosis="Table 1 Method A Score X：按可见三列复算 95.52，不是表中的 95.77；delta +0.25。",
        reported_value="95.77",
        visible_computed_value="95.52",
        delta="+0.25",
        aggregation_caveat="visible arithmetic mean only",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("must use severity `Blocker`" in error for error in errors):
        raise AssertionError(f"Expected numerical severity error, got {errors}")


def test_numerical_finding_must_include_concrete_values_in_diagnosis() -> None:
    module = load_module()
    finding = valid_finding(
        id="F2",
        diagnosis="Score X 与可见均值有偏差，需复查。",
        reported_value="95.77",
        visible_computed_value="95.52",
        delta="+0.25",
        aggregation_caveat="visible arithmetic mean only",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, _ = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if not any("reported_value" in error or "vague language" in error for error in errors):
        raise AssertionError(f"Expected concrete numeric diagnosis error, got {errors}")


def test_numerical_finding_can_use_directive_language_with_values() -> None:
    module = load_module()
    finding = valid_finding(
        id="F2",
        diagnosis="Table 3 Qwen2.5-32B MMMU Avg：按可见六列复算 37.64，不是表中的 47.70；delta +10.06。",
        reported_value="47.70",
        visible_computed_value="37.64",
        delta="+10.06",
        aggregation_caveat="deterministic gap; only a specific stated denominator/weighting explanation could rebut it",
    )
    path = write_json({"findings": [finding]})
    try:
        errors, warnings = module.audit_artifacts(path)
    finally:
        path.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Directive numeric finding with values should pass, got errors={errors}, warnings={warnings}")


def valid_issue_artifact(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "artifact_type": "ariadne_issue_artifact",
        "domain": "layout",
        "context_policy": "model_readable_issue_only",
        "producer": "layout_agent",
        "status": "completed",
        "skip_reason": "",
        "source_artifacts": [
            {
                "path": "layout_audit.json",
                "hash": "sha256:1234567890abcdef",
                "context_policy": "tool_only",
            }
        ],
        "coverage": {"checked": 1, "issues": 1, "skipped": 0},
        "issues": [
            {
                "local_id": "L1",
                "severity": "Major",
                "issue_type": "layout",
                "title": "Main table is cramped",
                "diagnosis": "The main result table is hard to scan.",
                "reader_friction": "The reader cannot compare the central evidence quickly.",
                "writing_principle": "低认知负担 / reader-first",
                "self_check": "Can the main comparison be read without zooming?",
                "evidence_refs": ["layout-p001-001"],
                "recommendation": "Simplify the table or move detail to appendix.",
                "confidence": "medium",
                "severity_rationale": "The issue affects the main evidence.",
                "downgrade_condition": "Readable main-table layout in the compiled PDF.",
                "render_hint": {"anchor": "page:1", "display_group": "compiled-display-checks"},
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_issue_artifact_schema_accepts_valid_payload() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        issues_dir = Path(tempdir)
        (issues_dir / "layout_issues.json").write_text(json.dumps(valid_issue_artifact()), encoding="utf-8")
        errors, warnings, ids = module.audit_issue_artifacts(issues_dir)
    if errors or warnings:
        raise AssertionError(f"Valid issue artifact should pass, errors={errors}, warnings={warnings}")
    if ids != {"layout:L1"}:
        raise AssertionError(f"Expected scoped issue id, got {ids}")


def test_issue_artifact_schema_rejects_missing_required_fields() -> None:
    module = load_module()
    payload = valid_issue_artifact()
    issue = payload["issues"][0]  # type: ignore[index]
    del issue["evidence_refs"]  # type: ignore[index]
    issue["render_hint"] = {}  # type: ignore[index]
    with tempfile.TemporaryDirectory() as tempdir:
        issues_dir = Path(tempdir)
        (issues_dir / "layout_issues.json").write_text(json.dumps(payload), encoding="utf-8")
        errors, _warnings, _ids = module.audit_issue_artifacts(issues_dir)
    expected = ("evidence_refs", "display_group")
    if not all(any(fragment in error for error in errors) for fragment in expected):
        raise AssertionError(f"Expected issue artifact schema errors, got {errors}")


def test_legacy_bundle_without_issue_artifacts_warns_only() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        issues_dir = Path(tempdir) / "issue_artifacts"
        errors, warnings, ids = module.audit_issue_artifacts(issues_dir)
    if errors or ids:
        raise AssertionError(f"Legacy missing issue_artifacts should not error, errors={errors}, ids={ids}")
    if not only_legacy_issue_artifact_warning(warnings):
        raise AssertionError(f"Expected legacy warning, got {warnings}")


def test_issue_artifacts_cli_can_run_without_findings() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        issues_dir = Path(tempdir)
        (issues_dir / "layout_issues.json").write_text(json.dumps(valid_issue_artifact()), encoding="utf-8")
        status = module.main(["--issue-artifacts", str(issues_dir)])
    if status != 0:
        raise AssertionError(f"Expected issue-artifacts-only CLI audit to pass, got status={status}")


def test_sharded_phase_a_requires_phase_b_synthesis_for_full_audit() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir)
        write_json_file = lambda name, payload: (bundle / name).write_text(json.dumps(payload), encoding="utf-8")
        write_json_file("phase_a_shard_manifest.json", {"context_policy": "model_readable_shard_manifest_only", "shards": [], "packet_paths": []})
        errors, warnings = module.audit_sharded_phase_completion(bundle, issue_artifacts_dir=bundle / "issue_artifacts")
        if not any("phase_b_context.json" in error for error in errors) or not any("whole_paper_findings.jsonl" in error for error in errors):
            raise AssertionError(f"Expected missing Phase B errors, got errors={errors}, warnings={warnings}")
        (bundle / "issue_artifacts").mkdir()
        write_json_file("phase_b_context.json", {"schema_version": 1})
        (bundle / "issue_artifacts" / "whole_paper_findings.jsonl").write_text("{}\n", encoding="utf-8")
        errors, warnings = module.audit_sharded_phase_completion(bundle, issue_artifacts_dir=bundle / "issue_artifacts")
    if errors:
        raise AssertionError(f"Completed sharded Phase B should pass guard, got errors={errors}, warnings={warnings}")


def test_strict_provenance_requires_agent_receipt() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir)
        findings = bundle / "findings.json"
        findings.write_text(json.dumps({"findings": [valid_finding()]}), encoding="utf-8")
        errors, _warnings = module.audit_artifacts(findings, bundle_path=bundle, strict_provenance=True)
    if not any("agent_provenance.json" in error for error in errors):
        raise AssertionError(f"Expected missing provenance error, got {errors}")


def test_strict_claim_links_are_errors() -> None:
    module = load_module()
    finding = write_json({"findings": [valid_finding(id="F1")]})
    claims = write_json(
        {
            "claims": [
                {
                    "claim_id": "C1",
                    "claim_text": "Claim",
                    "location": "Intro",
                    "claim_type": "fixture",
                    "strength": "strong",
                    "required_evidence": "Evidence",
                    "visible_evidence": "Evidence",
                    "status": "supported",
                    "next_draft_task": "None",
                    "linked_findings": ["WB001"],
                }
            ]
        }
    )
    try:
        errors, _warnings = module.audit_artifacts(finding, claims_path=claims, strict_provenance=True)
    finally:
        finding.unlink(missing_ok=True)
        claims.unlink(missing_ok=True)
    if not any("WB001" in error for error in errors):
        raise AssertionError(f"Expected broken claim link as strict error, got {errors}")


def test_strict_claim_links_accept_compiled_source_mapping() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir)
        issues = bundle / "issue_artifacts"
        issues.mkdir()
        findings = bundle / "findings.json"
        claims = bundle / "claims.json"
        findings.write_text(json.dumps({"findings": [valid_finding(id="F7")]}), encoding="utf-8")
        claims.write_text(
            json.dumps(
                {
                    "claims": [
                        {
                            "claim_id": "C1",
                            "claim_text": "Claim",
                            "location": "Intro",
                            "claim_type": "fixture",
                            "strength": "strong",
                            "required_evidence": "Evidence",
                            "visible_evidence": "Evidence",
                            "status": "supported",
                            "next_draft_task": "None",
                            "linked_findings": ["whole_paper:WB001"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (issues / "compiled_issue_index.json").write_text(
            json.dumps(
                {
                    "artifact_type": "ariadne_compiled_issue_index",
                    "schema_version": 1,
                    "source_to_finding_id": {"whole_paper:WB001": "F7"},
                    "normalized_jsonl_shards": [],
                }
            ),
            encoding="utf-8",
        )
        errors, _warnings = module.audit_artifacts(findings, claims_path=claims, bundle_path=bundle, strict_provenance=True)
    if any("whole_paper:WB001" in error for error in errors):
        raise AssertionError(f"Mapped source claim link should pass, got {errors}")


def test_coverage_requires_blind_spot_for_zero_effective_specialist() -> None:
    module = load_module()
    coverage = {
        "units": [{"unit": "Specialist issue artifacts", "total": 0, "reviewed": 0, "with_issues": 0, "clean": 0, "skipped": 0}],
        "issue_artifact_coverage": [
            {"domain": "numeric", "status": "completed_no_signals", "checked": 0, "issues": 0, "skip_reason": "no signals"}
        ],
        "known_blind_spots": [],
    }
    errors, _warnings = module.audit_specialist_blind_spots(coverage)
    if not any("known_blind_spots" in error and "numeric" in error for error in errors):
        raise AssertionError(f"Expected missing numeric blind spot error, got {errors}")


def test_phase_a_receipts_reject_nonmonotonic_and_unanchored_issues() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        bundle = Path(tempdir)
        issues = bundle / "issue_artifacts"
        issues.mkdir()
        (bundle / "main.review_units.jsonl").write_text(
            "\n".join(
                [
                    json.dumps({"kind": "paragraph", "paragraph_id": "p1", "section_id": "intro"}),
                    json.dumps({"kind": "paragraph", "paragraph_id": "p2", "section_id": "intro"}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (bundle / "paragraph_decisions.jsonl").write_text(
            json.dumps({"paragraph_id": "p2", "section_id": "intro"}) + "\n"
            + json.dumps({"paragraph_id": "p1", "section_id": "intro"}) + "\n",
            encoding="utf-8",
        )
        (bundle / "section_reflections.json").write_text(
            json.dumps({"sections": [{"section_id": "intro"}]}),
            encoding="utf-8",
        )
        (issues / "prose_issues.jsonl").write_text(json.dumps({"local_id": "P1", "section_id": "intro"}) + "\n", encoding="utf-8")
        coverage = {"requested_scope": "full paper main.tex"}
        errors, _warnings = module.audit_phase_a_receipts(bundle, coverage, strict=True)
    if not any("monotonic" in error for error in errors) or not any("missing anchor" in error for error in errors):
        raise AssertionError(f"Expected monotonic and anchor errors, got {errors}")


def test_issue_artifact_source_hash_is_recomputed_when_source_exists() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        issues_dir = Path(tempdir)
        raw = issues_dir / "layout_audit.json"
        raw.write_text('{"observations":[]}\n', encoding="utf-8")
        payload = valid_issue_artifact(
            source_artifacts=[
                {
                    "path": str(raw),
                    "hash": module.sha256_path(raw),
                    "context_policy": "tool_only",
                }
            ]
        )
        (issues_dir / "layout_issues.json").write_text(json.dumps(payload), encoding="utf-8")
        errors, warnings, ids = module.audit_issue_artifacts(issues_dir)
    if errors or warnings or ids != {"layout:L1"}:
        raise AssertionError(f"Expected issue artifact source hash to pass, errors={errors}, warnings={warnings}, ids={ids}")


def test_issue_artifact_source_hash_mismatch_is_error() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        issues_dir = Path(tempdir)
        raw = issues_dir / "layout_audit.json"
        raw.write_text('{"observations":[]}\n', encoding="utf-8")
        payload = valid_issue_artifact(
            source_artifacts=[
                {
                    "path": str(raw),
                    "hash": "sha256:" + "0" * 64,
                    "context_policy": "tool_only",
                }
            ]
        )
        (issues_dir / "layout_issues.json").write_text(json.dumps(payload), encoding="utf-8")
        errors, _warnings, _ids = module.audit_issue_artifacts(issues_dir)
    if not any("hash mismatch" in error for error in errors):
        raise AssertionError(f"Expected source hash mismatch error, got {errors}")


def test_compiled_issue_index_suppresses_jsonl_warning() -> None:
    module = load_module()
    with tempfile.TemporaryDirectory() as tempdir:
        issues_dir = Path(tempdir)
        shard = issues_dir / "prose_issues.jsonl"
        shard.write_text(
            json.dumps(
                {
                    "local_id": "P1",
                    "severity": "Minor",
                    "issue_type": "claim_boundary",
                    "title": "开头主张缺少证据边界",
                    "diagnosis": "这个句子给出主张，但没有说明对象、范围和证据边界。",
                    "reader_friction": "读者还不知道证据边界，就被要求接受这个主张。",
                    "writing_principle": "文字精确性先于 flow",
                    "self_check": "下一稿能否在这里写清对象、范围和证据边界？",
                    "confidence": "high",
                    "evidence_refs": [{"source_artifact": "review_units.jsonl", "anchor": "s1"}],
                    "severity_rationale": "该问题影响读者判断 claim 的可信度。",
                    "downgrade_condition": "补齐范围和证据边界后可降级。",
                    "section_id": "intro",
                    "target_anchors": ["s1"],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (issues_dir / "compiled_issue_index.json").write_text(
            json.dumps(
                {
                    "artifact_type": "ariadne_compiled_issue_index",
                    "schema_version": 1,
                    "normalized_jsonl_shards": [{"path": str(shard), "hash": "sha256:1234567890abcdef", "rows": 1}],
                }
            ),
            encoding="utf-8",
        )
        errors, warnings, _ids = module.audit_issue_artifacts(issues_dir)
    if errors or warnings:
        raise AssertionError(f"Compiled JSONL shard should not warn, errors={errors}, warnings={warnings}")


def test_numeric_audit_schema_is_checked() -> None:
    module = load_module()
    path = write_json(
        {
            "signal_count": 1,
            "signals": [
                {
                    "table_id": "Table 1",
                    "row_label": "Method A",
                    "reported_value": "95.77",
                    "visible_computed_value": "95.52",
                    "delta": "+0.25",
                    "required_severity": "Blocker",
                }
            ],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", numeric_audit_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("aggregation_caveat" in error for error in errors):
        raise AssertionError(f"Expected numeric audit aggregation_caveat error, got {errors}")


def test_numeric_audit_render_required_signal_requires_blocker_severity() -> None:
    module = load_module()
    path = write_json(
        {
            "signal_count": 1,
            "signals": [
                {
                    "table_id": "Table 1",
                    "row_label": "Method A",
                    "reported_value": "95.77",
                    "visible_computed_value": "95.52",
                    "delta": "+0.25",
                    "aggregation_caveat": "visible arithmetic mean only",
                    "required_severity": "Minor",
                }
            ],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", numeric_audit_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("required_severity" in error and "Blocker" in error for error in errors):
        raise AssertionError(f"Expected required_severity error, got {errors}")


def test_numeric_audit_signal_must_render_in_html() -> None:
    module = load_module()
    html = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with html:
        html.write(HTML.read_text(encoding="utf-8").replace("95.52", "95.51"))
    path = Path(html.name)
    try:
        errors, _ = module.audit_artifacts(
            ARTIFACTS / "findings.json",
            numeric_audit_path=ARTIFACTS / "numeric_audit.json",
            html_path=path,
        )
    finally:
        path.unlink(missing_ok=True)
    if not any("numeric signal not rendered" in error and "95.52" in error for error in errors):
        raise AssertionError(f"Expected missing rendered numeric signal error, got {errors}")


def test_numeric_audit_signal_requires_nearby_blocker_rendering() -> None:
    module = load_module()
    html = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with html:
        html.write(HTML.read_text(encoding="utf-8").replace('data-severity="blocker" data-issue-type="numeric"', 'data-severity="minor" data-issue-type="numeric"').replace("■ Blocker</span> F2", "● Minor</span> F2"))
    path = Path(html.name)
    try:
        errors, _ = module.audit_artifacts(
            ARTIFACTS / "findings.json",
            numeric_audit_path=ARTIFACTS / "numeric_audit.json",
            html_path=path,
        )
    finally:
        path.unlink(missing_ok=True)
    if not any("without nearby Blocker severity" in error for error in errors):
        raise AssertionError(f"Expected missing nearby Blocker severity error, got {errors}")


def test_pass_observations_schema_is_checked() -> None:
    module = load_module()
    path = write_json(
        {
            "pass_0_engagement_contract": [],
            "pass_1_cold_start_skim": [{"what_tripped_me": "missing location"}],
            "pass_2_linear_deep_read": [],
            "pass_3_section_reflections": [],
            "pass_4_whole_paper_argument": [],
            "pass_5_submission_walk": [],
            "pass_6_output_calibration": [],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", pass_observations_path=path)
    finally:
        path.unlink(missing_ok=True)
    if not any("missing `location`" in error for error in errors):
        raise AssertionError(f"Expected pass observation location error, got {errors}")


def test_render_manifest_rendered_section_must_exist_in_html() -> None:
    module = load_module()
    manifest = write_json(
        {
            "output_files": ["expected_html_report.html"],
            "sections": [{"id": "missing-section", "status": "rendered"}],
            "deferred_findings": [],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest, html_path=HTML)
    finally:
        manifest.unlink(missing_ok=True)
    if not any("missing-section" in error for error in errors):
        raise AssertionError(f"Expected missing rendered section error, got {errors}")


def test_render_manifest_paper_reader_requires_provenance() -> None:
    module = load_module()
    manifest = write_json(
        {
            "output_files": ["expected_html_report.html"],
            "sections": [{"id": "paper-reader", "status": "rendered"}],
            "deferred_findings": [],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest)
    finally:
        manifest.unlink(missing_ok=True)
    if not any("paper_reader" in error and "provenance" in error for error in errors):
        raise AssertionError(f"Expected missing paper_reader provenance error, got {errors}")


def test_render_manifest_source_integrity_check_is_enum() -> None:
    module = load_module()
    manifest = write_json(load_manifest(source_integrity_check="fixture-not-run"))
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest)
    finally:
        manifest.unlink(missing_ok=True)
    if not any("source_integrity_check" in error and "verified" in error for error in errors):
        raise AssertionError(f"Expected source_integrity_check enum error, got {errors}")


def test_render_manifest_skipped_integrity_emits_warning() -> None:
    module = load_module()
    manifest = write_json(load_manifest(source_integrity_check="skipped"))
    try:
        errors, warnings = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest)
    finally:
        manifest.unlink(missing_ok=True)
    if errors:
        raise AssertionError(f"Expected skipped source integrity to be warning-only, got errors={errors}")
    if not any("source integrity comparison was skipped" in warning for warning in warnings):
        raise AssertionError(f"Expected skipped source integrity warning, got {warnings}")


def test_render_manifest_mismatch_integrity_is_error() -> None:
    module = load_module()
    manifest = write_json(load_manifest(source_integrity_check="mismatch"))
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest)
    finally:
        manifest.unlink(missing_ok=True)
    if not any("source_integrity_check reports `mismatch`" in error for error in errors):
        raise AssertionError(f"Expected source integrity mismatch error, got {errors}")


def test_render_manifest_verified_recomputes_source_hash() -> None:
    module = load_module()
    manifest = write_json(load_manifest(source_hash="sha256:0000000000000000"))
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest, html_path=HTML, source_path=SOURCE)
    finally:
        manifest.unlink(missing_ok=True)
    if not any("source hash mismatch" in error for error in errors):
        raise AssertionError(f"Expected recomputed source hash mismatch, got {errors}")


def test_render_manifest_verified_compares_html_body_to_source() -> None:
    module = load_module()
    html = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8")
    with html:
        html.write(HTML.read_text(encoding="utf-8").replace("Our method solves this problem", "Our method reframes this problem"))
    html_path = Path(html.name)
    try:
        errors, _ = module.audit_artifacts(
            ARTIFACTS / "findings.json",
            manifest_path=ARTIFACTS / "render_manifest.json",
            html_path=html_path,
            source_path=SOURCE,
        )
    finally:
        html_path.unlink(missing_ok=True)
    if not any("body differs from source artifact" in error for error in errors):
        raise AssertionError(f"Expected HTML/source body mismatch, got {errors}")


def test_render_manifest_deferred_finding_must_exist_in_json() -> None:
    module = load_module()
    manifest = write_json(
        {
            "output_files": ["expected_html_report.html"],
            "sections": [{"id": "issue-index", "status": "rendered"}],
            "deferred_findings": ["F404"],
        }
    )
    try:
        errors, _ = module.audit_artifacts(ARTIFACTS / "findings.json", manifest_path=manifest)
    finally:
        manifest.unlink(missing_ok=True)
    if not any("unknown finding id" in error for error in errors):
        raise AssertionError(f"Expected unknown deferred finding error, got {errors}")


def main() -> int:
    test_review_artifact_fixture_passes_contract()
    test_bundle_cli_paths_pass_contract()
    test_high_risk_finding_requires_downgrade_condition()
    test_json_finding_must_render_or_be_deferred()
    test_artifact_only_json_finding_may_be_absent_from_html()
    test_skipped_coverage_requires_pending_marker()
    test_layout_sampled_pages_cannot_claim_full_coverage()
    test_layout_coverage_requires_layout_audit()
    test_layout_audit_provenance_is_checked()
    test_layout_audit_pdf_hash_is_recomputed_when_pdf_exists()
    test_layout_audit_rejects_missing_pdf_for_replay()
    test_layout_audit_replay_rejects_tampered_observations()
    test_layout_finding_requires_layout_audit_provenance()
    test_layout_finding_accepts_layout_audit_observation_id()
    test_pass_5_layout_observation_requires_explicit_provenance()
    test_forbidden_duplicate_artifacts_are_rejected()
    test_full_paper_annotations_must_not_be_top_issue_sample()
    test_full_paper_receipts_allow_sparse_visible_annotations()
    test_annotations_must_match_current_source_hash()
    test_issue_artifact_schema_accepts_valid_payload()
    test_issue_artifact_schema_rejects_missing_required_fields()
    test_legacy_bundle_without_issue_artifacts_warns_only()
    test_issue_artifacts_cli_can_run_without_findings()
    test_sharded_phase_a_requires_phase_b_synthesis_for_full_audit()
    test_strict_provenance_requires_agent_receipt()
    test_strict_claim_links_are_errors()
    test_strict_claim_links_accept_compiled_source_mapping()
    test_coverage_requires_blind_spot_for_zero_effective_specialist()
    test_phase_a_receipts_reject_nonmonotonic_and_unanchored_issues()
    test_issue_artifact_source_hash_is_recomputed_when_source_exists()
    test_issue_artifact_source_hash_mismatch_is_error()
    test_compiled_issue_index_suppresses_jsonl_warning()
    test_numerical_finding_requires_aggregation_caveat()
    test_numerical_finding_must_be_blocker()
    test_numerical_finding_must_include_concrete_values_in_diagnosis()
    test_numerical_finding_can_use_directive_language_with_values()
    test_numeric_audit_schema_is_checked()
    test_numeric_audit_render_required_signal_requires_blocker_severity()
    test_numeric_audit_signal_must_render_in_html()
    test_numeric_audit_signal_requires_nearby_blocker_rendering()
    test_pass_observations_schema_is_checked()
    test_render_manifest_rendered_section_must_exist_in_html()
    test_render_manifest_paper_reader_requires_provenance()
    test_render_manifest_source_integrity_check_is_enum()
    test_render_manifest_skipped_integrity_emits_warning()
    test_render_manifest_mismatch_integrity_is_error()
    test_render_manifest_verified_recomputes_source_hash()
    test_render_manifest_verified_compares_html_body_to_source()
    test_render_manifest_deferred_finding_must_exist_in_json()
    print("audit_review_artifacts regression tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
