#!/usr/bin/env python3
"""Regression tests for Ariadne issue-artifact compilation."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compile_review_artifacts.py"
AUDIT_SCRIPT = ROOT / "scripts" / "audit_review_artifacts.py"


def load_module(script: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prose_fields(anchor: str = "s-intro-p001-s001") -> dict[str, object]:
    return {
        "reader_friction": "读者还不知道证据边界，就被要求接受较强主张。",
        "writing_principle": "文字精确性先于 flow",
        "self_check": "下一稿能否在这里写清对象、范围和证据边界？",
        "evidence_refs": [{"source_artifact": "review_units.jsonl", "anchor": anchor}],
        "confidence": "high",
        "severity_rationale": "该问题影响读者判断 claim 的可信度。",
        "downgrade_condition": "补齐范围和证据边界后可降级。",
    }


def specialist_artifact(domain: str = "reference") -> dict[str, object]:
    return {
        "artifact_type": "ariadne_issue_artifact",
        "domain": domain,
        "context_policy": "model_readable_issue_only",
        "status": "completed",
        "source_artifacts": [
            {"path": f"{domain}_audit.json", "hash": "sha256:1234567890abcdef", "context_policy": "tool_only"}
        ],
        "coverage": {"checked": 3, "issues": 1, "skipped": 0},
        "issues": [
            {
                "local_id": "R1",
                "severity": "Major",
                "issue_type": "reference_format",
                "title": "Hidden DOI fields",
                "diagnosis": "Several cited entries use non-standard xdoi fields, so identifiers may not render.",
                "reader_friction": "Reviewers have to hunt for identifiers manually.",
                "writing_principle": "特定读者共同体",
                "self_check": "Do cited entries render DOI or URL fields in the bibliography?",
                "evidence_refs": ["bib:R1"],
                "confidence": "high",
                "severity_rationale": "Affects many cited references.",
                "downgrade_condition": "All cited identifiers render in the final bibliography.",
                "render_hint": {"anchor": "page:references", "display_group": "Reference Hygiene"},
            }
        ],
    }


def test_compile_jsonl_and_specialist_artifacts() -> None:
    module = load_module(SCRIPT, "compile_review_artifacts")
    audit = load_module(AUDIT_SCRIPT, "audit_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        issues = root / "issue_artifacts"
        issues.mkdir()
        (issues / "prose_issues.jsonl").write_text(
            json.dumps(
                {
                    "local_id": "P1",
                    "severity": "Minor",
                    "issue_type": "prose",
                    "title": "开头句主张缺少证据边界",
                    "diagnosis": "这个句子先给出较强主张，但没有说明它由哪些实验设置支撑。",
                    "target_anchors": ["s-intro-p001-s001"],
                    "spans_sections": False,
                    **prose_fields("s-intro-p001-s001"),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (issues / "whole_paper_findings.jsonl").write_text(
            json.dumps(
                {
                    "local_id": "W1",
                    "severity": "Major",
                    "issue_type": "claim_evidence",
                    "title": "整篇主张强于可见证据边界",
                    "diagnosis": "全稿叙述没有区分探索性证据和稳定结论，使中心 claim 显得比证据更强。",
                    "target_anchors": ["abstract", "experiments"],
                    "spans_sections": True,
                    "reader_friction": "读者可能接受观察到的趋势，却无法判断它是否足以支撑整篇层面的稳定主张。",
                    "writing_principle": "改变读者理解状态",
                    "self_check": "如果不补新证据，下一稿必须收窄哪一个中心 claim？",
                    "evidence_refs": [{"source_artifact": "phase_b_context.json", "anchor": "abstract"}],
                    "confidence": "medium",
                    "severity_rationale": "整篇 claim/evidence 边界不清会影响审稿人对贡献强度的判断。",
                    "downgrade_condition": "当摘要、实验和结论的 claim 边界一致后可降级。",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        write_json(issues / "reference_issues.json", specialist_artifact())

        findings, annotations, index = module.compile_artifacts(
            issues_dir=issues,
            source_artifact="paper.source.html",
            source_hash="sha256:aaaaaaaaaaaaaaaa",
        )

        if index["source_issue_count"] != 3 or index["finding_count"] != 3:
            raise AssertionError(f"Unexpected compile counts: {index}")
        if len(index["normalized_jsonl_shards"]) != 2:
            raise AssertionError(f"Expected JSONL shards to be normalized, got {index['normalized_jsonl_shards']}")
        if annotations["annotation_schema"] != "anchor-only":
            raise AssertionError(f"Expected anchor-only annotations, got {annotations}")
        if [item["id"] for item in findings["findings"]] != ["F1", "F2", "F3"]:
            raise AssertionError(f"Expected stable F ids, got {findings['findings']}")
        source_ids = [item["source_issue_ids"][0] for item in findings["findings"]]
        if source_ids != ["prose:P1", "whole_paper:W1", "reference:R1"]:
            raise AssertionError(f"Unexpected source issue ids: {source_ids}")
        visibility = [item["render_visibility"] for item in findings["findings"]]
        if visibility != ["student_visible", "student_visible", "artifact_only"]:
            raise AssertionError(f"Unexpected visibility classification: {visibility}")
        if [item["issue_id"] for item in annotations["annotations"]] != ["F1", "F2"]:
            raise AssertionError(f"Artifact-only reference finding should not create overlay annotation: {annotations}")
        if index["artifact_only_finding_ids"] != ["F3"]:
            raise AssertionError(f"Compiled index should record artifact-only findings: {index}")

        errors, warnings, _ids = audit.audit_findings(findings)
        if errors or warnings:
            raise AssertionError(f"Compiled findings should satisfy finding audit, errors={errors}, warnings={warnings}")
        errors, warnings = audit.audit_annotations(annotations, finding_ids={item["id"] for item in findings["findings"]})
        if errors:
            raise AssertionError(f"Compiled annotations should satisfy annotation audit, errors={errors}, warnings={warnings}")


def test_compiler_deduplicates_matching_evidence_refs() -> None:
    module = load_module(SCRIPT, "compile_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        issues = Path(tempdir) / "issue_artifacts"
        issues.mkdir()
        payload = specialist_artifact("layout")
        second = dict(payload["issues"][0])  # type: ignore[index]
        second["local_id"] = "R2"
        second["title"] = "Same issue repeated"
        payload["issues"].append(second)  # type: ignore[index,union-attr]
        payload["coverage"] = {"checked": 3, "issues": 2, "skipped": 0}
        write_json(issues / "layout_issues.json", payload)

        findings, _annotations, index = module.compile_artifacts(issues_dir=issues)

        if index["source_issue_count"] != 2 or index["finding_count"] != 1:
            raise AssertionError(f"Expected deduped finding, got {index}")
        source_ids = findings["findings"][0]["source_issue_ids"]
        if source_ids != ["layout:R1", "layout:R2"]:
            raise AssertionError(f"Expected merged source ids, got {source_ids}")


def test_compiler_allows_explicit_student_visible_specialist_issue() -> None:
    module = load_module(SCRIPT, "compile_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        issues = Path(tempdir) / "issue_artifacts"
        issues.mkdir()
        payload = specialist_artifact("source_hygiene")
        payload["issues"][0]["render_visibility"] = "student_visible"  # type: ignore[index]
        write_json(issues / "source_hygiene_issues.json", payload)

        findings, annotations, index = module.compile_artifacts(issues_dir=issues)

        if findings["findings"][0]["render_visibility"] != "student_visible":
            raise AssertionError(f"Explicit visibility should be preserved: {findings}")
        if len(annotations["annotations"]) != 1:
            raise AssertionError(f"Student-visible specialist issue should create annotation: {annotations}")
        if index["artifact_only_finding_ids"]:
            raise AssertionError(f"No artifact-only ids expected: {index}")


def test_compiler_hides_source_only_anonymous_front_matter_false_positive() -> None:
    module = load_module(SCRIPT, "compile_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        issues = Path(tempdir) / "issue_artifacts"
        issues.mkdir()
        (issues / "prose_issues.jsonl").write_text(
            json.dumps(
                {
                    "local_id": "P1",
                    "domain": "prose",
                    "severity": "Major",
                    "issue_type": "submission",
                    "title": "匿名评审模式下首页仍暴露作者身份",
                    "diagnosis": "正文入口处直接显示作者姓名、单位占位和邮箱占位；若这是 ACL review 版，匿名性在第一页已经破坏。",
                    "target_anchors": ["s-front-p001-s001"],
                    "render_visibility": "student_visible",
                    **prose_fields("s-front-p001-s001"),
                },
                ensure_ascii=False,
            )
            + "\n"
            + json.dumps(
                {
                    "local_id": "P2",
                    "domain": "prose",
                    "severity": "Major",
                    "issue_type": "submission",
                    "title": "匿名代码链接与首页身份风险叠加",
                    "diagnosis": "摘要末尾给出 anonymous.4open.science 链接，但首页作者姓名已经可见，且链接 slug 可能形成可追踪信号。",
                    "target_anchors": ["s-front-p001-s002"],
                    "render_visibility": "student_visible",
                    **prose_fields("s-front-p001-s002"),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        findings, annotations, index = module.compile_artifacts(issues_dir=issues)

        if [item["render_visibility"] for item in findings["findings"]] != ["artifact_only", "artifact_only"]:
            raise AssertionError(f"Source-only identity false positives should be audit-only: {findings}")
        if annotations["annotations"]:
            raise AssertionError(f"Audit-only identity false positives should not create annotations: {annotations}")
        if index["artifact_only_finding_ids"] != ["F1", "F2"]:
            raise AssertionError(f"Expected artifact-only ids for hidden false positives: {index}")


def test_compiler_keeps_compiled_pdf_identity_issue_visible() -> None:
    module = load_module(SCRIPT, "compile_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        issues = Path(tempdir) / "issue_artifacts"
        issues.mkdir()
        payload = specialist_artifact("source_hygiene")
        payload["issues"][0].update(  # type: ignore[index]
            {
                "local_id": "S1",
                "severity": "Major",
                "issue_type": "anonymity",
                "title": "Compiled submission still exposes identity/anonymity signals",
                "diagnosis": "compiled front matter: Jane Doe",
                "render_visibility": "student_visible",
                "visibility_basis": "compiled_pdf",
            }
        )
        write_json(issues / "source_hygiene_issues.json", payload)

        findings, annotations, index = module.compile_artifacts(issues_dir=issues)

        if findings["findings"][0]["render_visibility"] != "student_visible":
            raise AssertionError(f"Compiled PDF identity issue should stay visible: {findings}")
        if len(annotations["annotations"]) != 1:
            raise AssertionError(f"Compiled PDF identity issue should create annotation: {annotations}")
        if index["artifact_only_finding_ids"]:
            raise AssertionError(f"No artifact-only ids expected for compiled PDF identity issue: {index}")


def test_compiler_drops_stale_resolved_float_reference_issue() -> None:
    module = load_module(SCRIPT, "compile_review_artifacts")
    with tempfile.TemporaryDirectory() as tempdir:
        root = Path(tempdir)
        issues = root / "issue_artifacts"
        issues.mkdir()
        source = root / "paper.source.html"
        source.write_text(
            """
<html><body>
  <p><span data-sentence-id="s-demo">As shown in Figure <a data-reference="fig:demo" href="#fig:demo">2</a>, the result holds.</span></p>
  <figure id="fig:demo"><figcaption><strong>Figure 2: </strong>Demo caption.</figcaption></figure>
</body></html>
""",
            encoding="utf-8",
        )
        (issues / "prose_issues.jsonl").write_text(
            json.dumps(
                {
                    "local_id": "P1",
                    "domain": "prose",
                    "severity": "Major",
                    "issue_type": "figure_reference",
                    "title": "图号引用错误",
                    "diagnosis": "旧缓存声称这句话指向了错误图号，但当前 source HTML 已经解析为正确图。",
                    "target_anchors": ["s-demo"],
                    "primary_anchor": "s-demo",
                    "render_visibility": "student_visible",
                    **prose_fields("s-demo"),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

        findings, annotations, index = module.compile_artifacts(issues_dir=issues, source_artifact=str(source))

        if findings["findings"] or annotations["annotations"]:
            raise AssertionError(f"Resolved stale figure-reference issue should be dropped: {findings}, {annotations}")
        if index["stale_source_issue_ids"] != ["prose:P1"]:
            raise AssertionError(f"Stale issue id should be recorded in the index: {index}")


if __name__ == "__main__":
    test_compile_jsonl_and_specialist_artifacts()
    test_compiler_deduplicates_matching_evidence_refs()
    test_compiler_allows_explicit_student_visible_specialist_issue()
    test_compiler_hides_source_only_anonymous_front_matter_false_positive()
    test_compiler_keeps_compiled_pdf_identity_issue_visible()
    test_compiler_drops_stale_resolved_float_reference_issue()
    print("compile_review_artifacts regression tests passed")
