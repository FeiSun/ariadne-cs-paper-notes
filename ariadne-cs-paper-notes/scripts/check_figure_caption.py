#!/usr/bin/env python3
"""Audit source-level figure/table caption, label, and asset signals."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_paper_text import (  # noqa: E402
    PLACEHOLDER_RE,
    TODO_RE,
    ExtractionState,
    collect_tex_roots,
    expand_inputs,
    one_line,
    project_root_for,
    strip_latex_comments,
)
from check_page_layout import (  # noqa: E402
    BBoxParser,
    line_text,
    parse_pages,
    pdf_page_count,
    run_pdftotext_bbox,
)


TOOL_NAME = "scripts/check_figure_caption.py"
TOOL_VERSION = "1"

FLOAT_ENV_RE = re.compile(r"\\begin\{(figure|figure\*|wrapfigure|table|table\*)\}(.*?)\\end\{\1\}", re.DOTALL)
CAPTION_RE = re.compile(r"\\caption(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}", re.DOTALL)
LABEL_RE = re.compile(r"\\label\{([^{}]+)\}")
INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^{}]+)\}")
FIG_TABLE_REF_RE = re.compile(r"\\(?:ref|cref|Cref|autoref)\{([^{}]+)\}")
GRAPHIC_EXTENSIONS = ("", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".eps")
RASTER_GRAPHIC_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
PDF_GRAPHIC_EXTENSIONS = {".pdf"}
RENDERED_CAPTION_START_RE = re.compile(r"^\s*(?:Figure|Fig\.?|Table)\s+[A-Za-z]?\d+(?:\.\d+)?\s*[:.]?", re.IGNORECASE)
RENDERED_CAPTION_LABEL_RE = re.compile(r"^\s*(?:Figure|Fig\.?|Table)\s+[A-Za-z]?\d+(?:\.\d+)?\s*[:.]?\s*", re.IGNORECASE)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def compact_text(value: Any, *, max_chars: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def add_observation(
    observations: list[dict[str, Any]],
    *,
    issue_type: str,
    severity: str,
    title: str,
    evidence: str,
    recommendation: str,
    confidence: float,
    details: dict[str, Any] | None = None,
) -> None:
    observation: dict[str, Any] = {
        "observation_id": f"figure-caption-{len(observations) + 1:03d}",
        "issue_type": issue_type,
        "severity": severity,
        "title": title,
        "evidence": compact_text(evidence, max_chars=1400),
        "recommendation": recommendation,
        "confidence": confidence,
    }
    if details:
        observation["details"] = details
    observations.append(observation)


def renumber_observation_ids(observations: list[dict[str, Any]]) -> None:
    for idx, observation in enumerate(observations, 1):
        original_id = observation.get("observation_id")
        new_id = f"figure-caption-{idx:03d}"
        if original_id and original_id != new_id:
            details = observation.get("details")
            if not isinstance(details, dict):
                details = {}
            details.setdefault("original_observation_id", original_id)
            observation["details"] = details
        observation["observation_id"] = new_id


def load_source(source: Path) -> tuple[str, Path, list[Path], list[str]]:
    state = ExtractionState()
    tex_roots = collect_tex_roots(source, state) if source.suffix.lower() == ".tex" or source.is_dir() else [source]
    root = project_root_for(source)
    raw_chunks: list[str] = []
    for path in tex_roots:
        raw = expand_inputs(path, state, root=root) if path.suffix.lower() == ".tex" else path.read_text(encoding="utf-8", errors="replace")
        raw_chunks.append(raw)
    return "\n\n".join(raw_chunks), root, tex_roots, state.warnings


def candidate_graphic_paths(root: Path, graphic: str) -> list[Path]:
    raw_path = Path(graphic)
    bases = [raw_path] if raw_path.is_absolute() else [root / raw_path]
    candidates: list[Path] = []
    for base in bases:
        if base.suffix:
            candidates.append(base)
        else:
            candidates.extend(Path(str(base) + ext) for ext in GRAPHIC_EXTENSIONS if ext)
            candidates.append(base)
    return candidates


def graphic_exists(root: Path, graphic: str) -> bool:
    return any(path.exists() for path in candidate_graphic_paths(root, graphic))


def resolve_graphic_path(root: Path, graphic: str) -> Path | None:
    for path in candidate_graphic_paths(root, graphic):
        if path.exists() and path.is_file():
            return path
    return None


def caption_words(caption: str) -> int:
    return len(re.findall(r"\b[A-Za-z0-9][A-Za-z0-9'-]*\b", caption))


def ref_keys(raw: str) -> list[str]:
    keys: list[str] = []
    for match in FIG_TABLE_REF_RE.finditer(raw):
        keys.extend(item.strip() for item in match.group(1).split(",") if item.strip())
    return keys


def audit_figure_captions(raw: str, root: Path, *, max_items: int = 80) -> tuple[list[dict[str, Any]], dict[str, int]]:
    observations: list[dict[str, Any]] = []
    source = strip_latex_comments(raw)
    floats = list(FLOAT_ENV_RE.finditer(source))
    all_labels = set(LABEL_RE.findall(source))
    figure_table_labels = {label for label in all_labels if label.lower().startswith(("fig:", "figure:", "tab:", "table:"))}

    missing_caption: list[str] = []
    missing_label: list[str] = []
    short_caption: list[str] = []
    placeholder_caption: list[str] = []
    missing_graphics: list[str] = []

    for idx, match in enumerate(floats, 1):
        env = match.group(1)
        body = match.group(2)
        captions = [one_line(item.group(1)) for item in CAPTION_RE.finditer(body)]
        labels = LABEL_RE.findall(body)
        graphics = [one_line(item.group(1)) for item in INCLUDEGRAPHICS_RE.finditer(body)]
        label_text = labels[0] if labels else f"{env} #{idx}"
        if not captions:
            missing_caption.append(f"{env} {idx} ({label_text})")
        else:
            for caption in captions:
                if not caption_words(caption):
                    missing_caption.append(f"{env} {idx} ({label_text}) has an empty caption")
                elif caption_words(caption) < 8:
                    short_caption.append(f"{env} {idx} ({label_text}): {caption}")
                if TODO_RE.search(caption) or PLACEHOLDER_RE.search(caption):
                    placeholder_caption.append(f"{env} {idx} ({label_text}): {caption}")
        if not labels:
            missing_label.append(f"{env} {idx}")
        for graphic in graphics:
            if not graphic_exists(root, graphic):
                missing_graphics.append(f"{env} {idx} ({label_text}) includes missing graphic `{graphic}`")

    references = [key for key in ref_keys(source) if key.lower().startswith(("fig:", "figure:", "tab:", "table:"))]
    unresolved_refs = sorted(set(key for key in references if key not in figure_table_labels))

    if missing_caption:
        add_observation(
            observations,
            issue_type="missing_caption",
            severity="medium",
            title="Figure/table floats are missing captions",
            evidence="; ".join(missing_caption[:max_items]),
            recommendation="Give every evidence-bearing figure/table a caption that states what the reader should learn.",
            confidence=0.9,
            details={"items": missing_caption[:max_items]},
        )
    if short_caption:
        add_observation(
            observations,
            issue_type="thin_caption",
            severity="low",
            title="Captions look too short to carry a takeaway",
            evidence="; ".join(short_caption[:max_items]),
            recommendation="Expand thin captions so they identify the setup, metric, and intended takeaway when needed.",
            confidence=0.72,
            details={"items": short_caption[:max_items]},
        )
    if placeholder_caption:
        add_observation(
            observations,
            issue_type="caption_placeholder",
            severity="high",
            title="Caption text contains placeholder or TODO markers",
            evidence="; ".join(placeholder_caption[:max_items]),
            recommendation="Resolve caption placeholders before review submission.",
            confidence=0.94,
            details={"items": placeholder_caption[:max_items]},
        )
    if missing_label:
        add_observation(
            observations,
            issue_type="missing_label",
            severity="low",
            title="Figure/table floats are missing labels",
            evidence="; ".join(missing_label[:max_items]),
            recommendation="Add labels to floats that may need stable cross-references or reviewer discussion.",
            confidence=0.76,
            details={"items": missing_label[:max_items]},
        )
    if unresolved_refs:
        add_observation(
            observations,
            issue_type="unresolved_float_reference",
            severity="medium",
            title="Figure/table references point to labels not defined in visible source",
            evidence="; ".join(unresolved_refs[:max_items]),
            recommendation="Define the referenced figure/table labels or correct the references.",
            confidence=0.88,
            details={"labels": unresolved_refs[:max_items]},
        )
    if missing_graphics:
        add_observation(
            observations,
            issue_type="missing_graphic_asset",
            severity="high",
            title="Included graphic files are missing from the source tree",
            evidence="; ".join(missing_graphics[:max_items]),
            recommendation="Add the missing graphic assets or fix the `\\includegraphics` paths before compiling/submitting.",
            confidence=0.88,
            details={"items": missing_graphics[:max_items]},
        )

    coverage = {
        "floats": len(floats),
        "captions": len(CAPTION_RE.findall(source)),
        "figure_table_labels": len(figure_table_labels),
        "figure_table_references": len(references),
        "includegraphics": len(INCLUDEGRAPHICS_RE.findall(source)),
        "signals_checked": len(missing_caption)
        + len(short_caption)
        + len(placeholder_caption)
        + len(missing_label)
        + len(unresolved_refs)
        + len(missing_graphics),
    }
    return observations, coverage


def included_graphics(raw: str) -> list[str]:
    source = strip_latex_comments(raw)
    return [one_line(match.group(1)) for match in INCLUDEGRAPHICS_RE.finditer(source)]


def collect_asset_quality_signals(
    *,
    name: str,
    width: int,
    height: int,
    mean: float,
    stddev: float,
    extrema: tuple[int, int] | tuple[float, float],
    check_resolution: bool,
    low_resolution: list[str],
    extreme_aspect: list[str],
    near_blank: list[str],
    low_contrast: list[str],
) -> int:
    signals = 0
    pixels = width * height
    aspect = max(width / max(height, 1), height / max(width, 1))
    label = f"{name} ({width}x{height})"
    if check_resolution and (width < 450 or height < 260 or pixels < 180_000):
        low_resolution.append(label)
        signals += 1
    if aspect >= 4.5:
        extreme_aspect.append(f"{label}, aspect={aspect:.2f}")
        signals += 1
    if stddev < 4.0 and (mean > 245 or mean < 10):
        near_blank.append(f"{label}, mean={mean:.1f}, stddev={stddev:.1f}, extrema={extrema}")
        signals += 1
    elif stddev < 12.0:
        low_contrast.append(f"{label}, stddev={stddev:.1f}, extrema={extrema}")
        signals += 1
    return signals


def render_pdf_asset_preview(pdf: Path, out_prefix: Path, pdftoppm_bin: str) -> Path:
    result = subprocess.run(
        [pdftoppm_bin, "-f", "1", "-l", "1", "-singlefile", "-png", "-r", "150", str(pdf), str(out_prefix)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = compact_text(result.stderr or result.stdout or f"pdftoppm exited with {result.returncode}", max_chars=300)
        raise RuntimeError(detail)
    rendered = out_prefix.with_suffix(".png")
    if not rendered.exists():
        raise RuntimeError("pdftoppm did not produce a PNG preview")
    return rendered


def audit_figure_asset_quality(
    raw: str,
    root: Path,
    *,
    pdftoppm: str | None = None,
    max_items: int = 80,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    observations: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        from PIL import Image, ImageStat  # type: ignore
    except Exception:
        return [], {
            "raster_assets_checked": 0,
            "pdf_figure_assets_checked": 0,
            "raster_asset_signals_checked": 0,
            "pdf_figure_asset_signals_checked": 0,
        }, ["Pillow is unavailable; figure asset quality checks were skipped."]

    pdftoppm_bin = shutil.which("pdftoppm") if pdftoppm is None else pdftoppm
    seen: set[Path] = set()
    low_resolution: list[str] = []
    extreme_aspect: list[str] = []
    near_blank: list[str] = []
    low_contrast: list[str] = []
    unreadable: list[str] = []
    skipped_pdf_without_renderer = 0
    raster_checked = 0
    pdf_checked = 0
    raster_signals = 0
    pdf_signals = 0

    with tempfile.TemporaryDirectory(prefix="ariadne-figure-assets-") as tempdir:
        temp_root = Path(tempdir)
        for graphic in included_graphics(raw):
            path = resolve_graphic_path(root, graphic)
            if path is None or path.resolve() in seen:
                continue
            resolved = path.resolve()
            seen.add(resolved)
            suffix = path.suffix.lower()
            display_name = path.name
            check_resolution = suffix in RASTER_GRAPHIC_EXTENSIONS
            image_path = path

            if suffix in PDF_GRAPHIC_EXTENSIONS:
                if not pdftoppm_bin:
                    skipped_pdf_without_renderer += 1
                    continue
                preview_prefix = temp_root / f"pdf_asset_{pdf_checked + len(unreadable) + 1}"
                try:
                    image_path = render_pdf_asset_preview(path, preview_prefix, pdftoppm_bin)
                except Exception as exc:
                    unreadable.append(f"{path.name}: PDF preview failed: {exc}")
                    continue
                display_name = f"{path.name} [PDF preview]"
                check_resolution = False
            elif suffix not in RASTER_GRAPHIC_EXTENSIONS:
                continue

            try:
                with Image.open(image_path) as image:
                    gray = image.convert("L")
                    width, height = image.size
                    stat = ImageStat.Stat(gray)
                    mean = float(stat.mean[0])
                    stddev = float(stat.stddev[0])
                    extrema = gray.getextrema()
            except Exception as exc:
                unreadable.append(f"{path.name}: {exc}")
                continue

            signals = collect_asset_quality_signals(
                name=display_name,
                width=width,
                height=height,
                mean=mean,
                stddev=stddev,
                extrema=extrema,
                check_resolution=check_resolution,
                low_resolution=low_resolution,
                extreme_aspect=extreme_aspect,
                near_blank=near_blank,
                low_contrast=low_contrast,
            )
            if suffix in PDF_GRAPHIC_EXTENSIONS:
                pdf_checked += 1
                pdf_signals += signals
            else:
                raster_checked += 1
                raster_signals += signals

    if low_resolution:
        add_observation(
            observations,
            issue_type="low_resolution_figure_asset",
            severity="medium",
            title="Raster figure assets look low-resolution for inspection",
            evidence="; ".join(low_resolution[:max_items]),
            recommendation="Regenerate these figures at higher resolution or use vector/PDF assets when possible.",
            confidence=0.82,
            details={"items": low_resolution[:max_items]},
        )
    if extreme_aspect:
        add_observation(
            observations,
            issue_type="extreme_aspect_figure_asset",
            severity="low",
            title="Raster figure assets have extreme aspect ratios",
            evidence="; ".join(extreme_aspect[:max_items]),
            recommendation="Inspect whether these figures will remain readable in the manuscript column width.",
            confidence=0.72,
            details={"items": extreme_aspect[:max_items]},
        )
    if near_blank:
        add_observation(
            observations,
            issue_type="near_blank_figure_asset",
            severity="high",
            title="Raster figure assets appear nearly blank",
            evidence="; ".join(near_blank[:max_items]),
            recommendation="Verify that the figure export contains the intended plot/table content and is not a blank placeholder.",
            confidence=0.86,
            details={"items": near_blank[:max_items]},
        )
    if low_contrast:
        add_observation(
            observations,
            issue_type="low_contrast_figure_asset",
            severity="medium",
            title="Raster figure assets have low grayscale contrast",
            evidence="; ".join(low_contrast[:max_items]),
            recommendation="Increase contrast, line weight, or label darkness so the figure remains readable in print/PDF.",
            confidence=0.7,
            details={"items": low_contrast[:max_items]},
        )
    if unreadable:
        warnings.append("Some figure assets could not be opened or previewed: " + "; ".join(unreadable[:max_items]))
    if skipped_pdf_without_renderer:
        warnings.append(
            f"{skipped_pdf_without_renderer} PDF figure asset(s) were skipped because pdftoppm is unavailable."
        )

    coverage = {
        "raster_assets_checked": raster_checked,
        "pdf_figure_assets_checked": pdf_checked,
        "raster_asset_signals_checked": raster_signals,
        "pdf_figure_asset_signals_checked": pdf_signals,
    }
    return observations, coverage, warnings


def audit_raster_asset_quality(
    raw: str,
    root: Path,
    *,
    max_items: int = 80,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    return audit_figure_asset_quality(raw, root, pdftoppm="", max_items=max_items)


def line_bbox(line: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(line.get("xMin", 0)),
        float(line.get("yMin", 0)),
        float(line.get("xMax", 0)),
        float(line.get("yMax", 0)),
    )


def rendered_caption_tail(text: str) -> str:
    return RENDERED_CAPTION_LABEL_RE.sub("", text, count=1).strip()


def analyze_rendered_caption_pages(
    parsed_pages: list[tuple[int, dict[str, Any]]],
    *,
    source_caption_count: int,
    pages_all: bool,
    max_items: int = 80,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    observations: list[dict[str, Any]] = []
    rendered_captions: list[dict[str, Any]] = []
    edge_items: list[str] = []
    label_only_items: list[str] = []

    for page_number, page in parsed_pages:
        width = float(page.get("width") or 0)
        height = float(page.get("height") or 0)
        if width <= 0 or height <= 0:
            continue
        edge_margin = max(18.0, width * 0.035)
        bottom_margin = max(22.0, height * 0.035)
        lines = [line for line in page.get("lines", []) if line_text(line)]
        lines.sort(key=lambda item: (float(item.get("yMin", 0)), float(item.get("xMin", 0))))
        for line in lines:
            text = line_text(line)
            if not RENDERED_CAPTION_START_RE.match(text):
                continue
            x_min, y_min, x_max, y_max = line_bbox(line)
            rendered_captions.append({"page": page_number, "text": text, "bbox": [x_min, y_min, x_max, y_max]})
            if x_min < edge_margin or x_max > width - edge_margin or y_max > height - bottom_margin:
                edge_items.append(
                    f"page {page_number}: `{compact_text(text, max_chars=160)}` bbox=({x_min:.1f},{y_min:.1f},{x_max:.1f},{y_max:.1f})"
                )
            if caption_words(rendered_caption_tail(text)) < 4:
                label_only_items.append(f"page {page_number}: `{compact_text(text, max_chars=160)}`")

    rendered_caption_count = len(rendered_captions)
    if source_caption_count and pages_all and rendered_caption_count == 0:
        add_observation(
            observations,
            issue_type="rendered_caption_missing",
            severity="high",
            title="Source captions are not visible as rendered Figure/Table captions",
            evidence=f"Source contains {source_caption_count} caption(s), but no rendered Figure/Table caption labels were detected in the checked PDF pages.",
            recommendation="Inspect the compiled PDF and caption package settings; make sure figure/table captions render visibly and are extractable.",
            confidence=0.78,
            details={"source_caption_count": source_caption_count, "rendered_caption_count": rendered_caption_count},
        )
    elif source_caption_count and pages_all and source_caption_count - rendered_caption_count > 1:
        add_observation(
            observations,
            issue_type="rendered_caption_count_mismatch",
            severity="medium",
            title="Fewer rendered Figure/Table captions were detected than source captions",
            evidence=f"Source contains {source_caption_count} caption(s), but only {rendered_caption_count} rendered Figure/Table caption label(s) were detected.",
            recommendation="Check whether captions are suppressed, unnumbered, hidden in graphics, or lost during compilation.",
            confidence=0.7,
            details={"source_caption_count": source_caption_count, "rendered_caption_count": rendered_caption_count},
        )
    if edge_items:
        add_observation(
            observations,
            issue_type="rendered_caption_edge_risk",
            severity="medium",
            title="Rendered caption text sits close to the page edge",
            evidence="; ".join(edge_items[:max_items]),
            recommendation="Inspect these pages for clipped captions, overfull lines, or captions pushed into margins.",
            confidence=0.82,
            details={"items": edge_items[:max_items]},
        )
    if label_only_items:
        add_observation(
            observations,
            issue_type="rendered_caption_label_only",
            severity="low",
            title="Rendered caption lines appear to contain only a label or very little takeaway text",
            evidence="; ".join(label_only_items[:max_items]),
            recommendation="Confirm that the full caption text is visible and not separated, clipped, or too thin to guide the reader.",
            confidence=0.64,
            details={"items": label_only_items[:max_items]},
        )

    coverage = {
        "rendered_pages_checked": len(parsed_pages),
        "rendered_captions_detected": rendered_caption_count,
        "rendered_caption_signals_checked": len(edge_items) + len(label_only_items),
    }
    return observations, coverage


def audit_rendered_pdf(
    pdf: Path,
    *,
    pages_value: str,
    source_caption_count: int,
    pdftotext: str | None,
    max_items: int = 80,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    warnings: list[str] = []
    pdftotext_bin = pdftotext or shutil.which("pdftotext")
    if not pdftotext_bin:
        return [], {"rendered_pages_checked": 0, "rendered_captions_detected": 0, "rendered_caption_signals_checked": 0}, [
            "pdftotext is unavailable; rendered figure/caption geometry checks were skipped."
        ]
    try:
        total_pages = pdf_page_count(pdf)
        pages = parse_pages(pages_value, total_pages)
        raw = run_pdftotext_bbox(pdf, pages, pdftotext_bin)
    except Exception as exc:
        return [], {"rendered_pages_checked": 0, "rendered_captions_detected": 0, "rendered_caption_signals_checked": 0}, [
            f"Rendered figure/caption geometry checks failed: {exc}"
        ]
    parser = BBoxParser()
    parser.feed(raw)
    parsed_pages = list(zip(pages, parser.pages))
    observations, coverage = analyze_rendered_caption_pages(
        parsed_pages,
        source_caption_count=source_caption_count,
        pages_all=len(pages) == total_pages,
        max_items=max_items,
    )
    coverage["rendered_pages_total"] = total_pages
    coverage["rendered_pages_requested"] = len(pages)
    if len(parsed_pages) != len(pages):
        warnings.append("pdftotext returned fewer rendered pages than requested for figure/caption geometry checks.")
    return observations, coverage, warnings


def build_payload(
    source: Path,
    *,
    pdf: Path | None = None,
    pages: str = "all",
    pdftotext: str | None = None,
    pdftoppm: str | None = None,
    max_items: int = 80,
) -> dict[str, Any]:
    raw, root, tex_roots, warnings = load_source(source)
    observations, coverage = audit_figure_captions(raw, root, max_items=max_items)
    asset_observations, asset_coverage, asset_warnings = audit_figure_asset_quality(
        raw,
        root,
        pdftoppm=pdftoppm,
        max_items=max_items,
    )
    observations.extend(asset_observations)
    coverage.update(asset_coverage)
    warnings.extend(asset_warnings)
    rendered_coverage: dict[str, int] = {}
    if pdf is not None:
        rendered_observations, rendered_coverage, rendered_warnings = audit_rendered_pdf(
            pdf,
            pages_value=pages,
            source_caption_count=int(coverage.get("captions", 0)),
            pdftotext=pdftotext,
            max_items=max_items,
        )
        observations.extend(rendered_observations)
        warnings.extend(rendered_warnings)
    renumber_observation_ids(observations)
    coverage.update(rendered_coverage)
    source_artifacts = [{"path": str(path), "hash": sha256_path(path)} for path in tex_roots if path.exists()]
    if source not in tex_roots and source.exists():
        source_artifacts.insert(0, {"path": str(source), "hash": sha256_path(source)})
    if pdf is not None and pdf.exists():
        source_artifacts.append({"path": str(pdf), "hash": sha256_path(pdf)})
    return {
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "script_hash": sha256_path(Path(__file__).resolve()),
        "checked_source": str(source),
        "checked_pdf": str(pdf) if pdf is not None else "",
        "source_artifacts": source_artifacts,
        "coverage": coverage,
        "observations": observations,
        "warnings": warnings,
        "limitations": [
            "Source-level caption/label/asset checks are deterministic and do not judge figure semantics.",
            "Figure asset quality checks measure local raster assets and first-page PDF previews only; they do not judge whether the figure supports the paper's claim.",
            "Rendered caption geometry checks use extractable PDF text and can miss captions embedded as images or unusual macros.",
            "Thin-caption signals are heuristic and should be confirmed by a figure/caption specialist or prose reviewer.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="LaTeX entry file or project directory")
    parser.add_argument("--pdf", type=Path, help="Optional compiled PDF for rendered caption geometry checks")
    parser.add_argument("--pages", default="all", help="Rendered PDF page list/ranges such as `1-3,8`; default all")
    parser.add_argument("--pdftotext", help="Path to pdftotext; defaults to PATH lookup")
    parser.add_argument("--pdftoppm", help="Path to pdftoppm; defaults to PATH lookup for PDF figure asset previews")
    parser.add_argument("--out", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--max-items", type=int, default=80)
    args = parser.parse_args(argv)

    source = args.source.expanduser().resolve()
    if not source.exists():
        parser.error(f"source does not exist: {source}")
    pdf = args.pdf.expanduser().resolve() if args.pdf else None
    if pdf is not None and not pdf.exists():
        parser.error(f"PDF does not exist: {pdf}")
    try:
        payload = build_payload(
            source,
            pdf=pdf,
            pages=args.pages,
            pdftotext=args.pdftotext,
            pdftoppm=args.pdftoppm,
            max_items=args.max_items,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
