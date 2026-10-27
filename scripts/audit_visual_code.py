#!/usr/bin/env python3
"""Heuristic scan for common "AI-generated visual" signals in a web artifact.

This is a candidate finder, not a verdict. It reads source files only; it does
not render the page, compute contrast, or judge whether a motion is meaningful.
Confirm every finding against the rendered result.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

TOOL_VERSION = "0.1.0"
SUPPORTED_SUFFIXES = {
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".astro",
}
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".cache",
    ".turbo",
    "node_modules",
    "bower_components",
    "dist",
    "build",
    "out",
    "coverage",
    "vendor",
    "target",
    "tmp",
}
SKIP_FILE_MARKERS = (".min.", ".map")
TEXT_LIMIT = 240

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}
PASS_ORDER = ["frame", "copy", "containers", "color", "type", "focus", "motion"]

GENERIC_PHRASES = [
    "ai-powered",
    "cutting-edge",
    "game-changing",
    "next-generation",
    "revolutionary",
    "seamless",
    "unlock",
    "elevate",
    "empower",
    "reimagine",
    "supercharge",
    "赋能",
    "一站式",
    "极致",
    "全新升级",
    "开启未来",
    "重新定义",
    "颠覆",
]

PLACEHOLDER_PHRASES = [
    "lorem ipsum",
    "placeholder text",
    "todo:",
    "待补充",
    "示例文本",
    "这里放",
    "文案待定",
]

EYEBROW_CLASS_RE = re.compile(
    r"(?:eyebrow|kicker|overline|pretitle|pre-title)", re.I
)

MANUAL_CHECKS = [
    "3-second focus: can a viewer name the one thing this screen/shot is about?",
    "Optical alignment: icons, labels, and baselines at the final viewing size.",
    "Contrast: measure body text and UI boundaries against their real backgrounds.",
    "Copy meaning: remove repetition only after preserving facts, labels, and legal text.",
    "Motion purpose: every animation should guide, reveal, show change, maintain continuity, or give feedback.",
    "Responsive states: narrow width, long copy, hover/focus, empty/error states, reduced motion.",
]


@dataclass
class Finding:
    rule: str
    pass_name: str
    severity: str
    message: str
    path: str
    line: int
    evidence: str
    repair: str

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "pass": self.pass_name,
            "severity": self.severity,
            "message": self.message,
            "path": self.path,
            "line": self.line,
            "evidence": self.evidence,
            "repair": self.repair,
        }


def trim(value: str, limit: int = TEXT_LIMIT) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def line_evidence(text: str, line: int) -> str:
    lines = text.splitlines()
    if 1 <= line <= len(lines):
        return trim(lines[line - 1])
    return ""


def add_finding(
    findings: list[Finding],
    seen: set[tuple[str, int, str]],
    *,
    rule: str,
    pass_name: str,
    severity: str,
    message: str,
    path: str,
    line: int,
    evidence: str,
    repair: str,
) -> None:
    key = (path, line, rule)
    if key in seen:
        return
    seen.add(key)
    findings.append(
        Finding(
            rule=rule,
            pass_name=pass_name,
            severity=severity,
            message=message,
            path=path,
            line=line,
            evidence=trim(evidence),
            repair=repair,
        )
    )


def strip_tags(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return trim(html.unescape(value))


def normalize_copy(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    return value


def unique_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def iter_source_files(targets: list[str]) -> tuple[list[Path], list[str], list[Path]]:
    files: list[Path] = []
    notes: list[str] = []
    bases: list[Path] = []
    for raw in targets:
        path = Path(raw).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Target not found: {path}")
        if path.is_file():
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError(f"Unsupported file type: {path.suffix or '(none)'} at {path}")
            files.append(path)
            bases.append(path.parent)
            continue
        if not path.is_dir():
            raise ValueError(f"Target is neither a file nor a directory: {path}")
        bases.append(path)
        for root, dirs, names in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(names):
                candidate = Path(root) / name
                lower = name.lower()
                if any(marker in lower for marker in SKIP_FILE_MARKERS):
                    continue
                if candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                if candidate.is_symlink():
                    continue
                try:
                    if candidate.stat().st_size > 2_000_000:
                        notes.append(f"Skipped large file: {candidate}")
                        continue
                except OSError:
                    continue
                files.append(candidate)
    unique = sorted({f.resolve() for f in files})
    if len(unique) > 2500:
        notes.append(f"File limit reached: scanning first 2500 of {len(unique)} files.")
        unique = unique[:2500]
    return unique, notes, bases


def display_path(path: Path, bases: list[Path]) -> str:
    for base in bases:
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return path.name


def scan_copy(
    text: str,
    rel: str,
    findings: list[Finding],
    seen: set[tuple[str, int, str]],
) -> None:
    if not rel.lower().endswith((".html", ".htm", ".vue", ".svelte", ".astro")):
        return

    # Decorative eyebrow / kicker immediately before a heading.
    element_re = re.compile(r"<(p|span|div|small)\b([^>]*)>(.*?)</\1>", re.I | re.S)
    for match in element_re.finditer(text):
        attrs = match.group(2)
        if not EYEBROW_CLASS_RE.search(attrs):
            continue
        label = strip_tags(match.group(3))
        if not (0 < len(label) <= 80):
            continue
        after = text[match.end() : match.end() + 600]
        if not re.match(r"\s*<h[12]\b", after, re.I):
            continue
        line = line_number(text, match.start())
        add_finding(
            findings,
            seen,
            rule="copy.eyebrow",
            pass_name="copy",
            severity="medium",
            message="Decorative eyebrow/kicker sits above a heading; confirm it adds category or context.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Delete it if it only decorates or repeats the heading; keep it only when it carries real category, date, or provenance.",
        )

    # Heading followed by a near-duplicate subtitle.
    heading_re = re.compile(r"<(h[12])\b[^>]*>(.*?)</\1>", re.I | re.S)
    next_block_re = re.compile(r"\s*<(p|div|span|small)\b[^>]*>(.*?)</\1>", re.I | re.S)
    for match in heading_re.finditer(text):
        heading_text = strip_tags(match.group(2))
        if not (8 <= len(heading_text) <= 80):
            continue
        next_match = next_block_re.match(text, match.end())
        if not next_match:
            continue
        body_text = strip_tags(next_match.group(2))
        if not (10 <= len(body_text) <= 220):
            continue
        left = normalize_copy(heading_text)
        right = normalize_copy(body_text)
        if not left or not right:
            continue
        ratio = SequenceMatcher(None, left, right).ratio()
        left_chars = set(left)
        right_chars = set(right)
        char_coverage = len(left_chars & right_chars) / max(1, len(left_chars))
        if ratio < 0.78 and char_coverage < 0.82:
            continue
        line = line_number(text, match.start())
        add_finding(
            findings,
            seen,
            rule="copy.repeated-heading",
            pass_name="copy",
            severity="medium",
            message="The block after the heading appears to restate it.",
            path=rel,
            line=line,
            evidence=f"{trim(heading_text, 90)} / {trim(body_text, 120)}",
            repair="Keep the heading, replace the restatement with one new supporting fact, or remove it.",
        )

    # Generic hype language.
    visible = strip_tags(text)
    generic_hits = []
    for phrase in GENERIC_PHRASES:
        if re.search(r"[A-Za-z]", phrase):
            if re.search(rf"\b{re.escape(phrase)}\b", visible, re.I):
                generic_hits.append(phrase)
        elif phrase in visible:
            generic_hits.append(phrase)
    if generic_hits:
        first = generic_hits[0]
        position = text.lower().find(first.lower())
        line = line_number(text, max(0, position))
        add_finding(
            findings,
            seen,
            rule="copy.generic-phrase",
            pass_name="copy",
            severity="low",
            message="Generic hype or filler language is present.",
            path=rel,
            line=line,
            evidence=", ".join(generic_hits[:6]),
            repair="Replace with a concrete claim, number, or noun; delete if it adds no information.",
        )

    placeholder_hits = [phrase for phrase in PLACEHOLDER_PHRASES if phrase in visible.lower()]
    if placeholder_hits:
        position = text.lower().find(placeholder_hits[0])
        line = line_number(text, max(0, position))
        add_finding(
            findings,
            seen,
            rule="copy.placeholder",
            pass_name="copy",
            severity="high" if "lorem ipsum" in placeholder_hits else "medium",
            message="Placeholder copy may still be visible.",
            path=rel,
            line=line,
            evidence=", ".join(placeholder_hits),
            repair="Replace with real content or remove the block; do not ship visible placeholders.",
        )


def scan_containers(
    text: str,
    rel: str,
    findings: list[Finding],
    seen: set[tuple[str, int, str]],
) -> None:
    class_values = re.findall(r"class(?:Name)?\s*=\s*[\"']([^\"']+)[\"']", text, re.I)
    card_count = sum(
        1
        for value in class_values
        if re.search(r"(?:^|\s)(?:card|panel|tile|stat-card|feature-card)(?:\s|$)", value, re.I)
    )
    shadow_lines = [
        line_number(text, m.start())
        for m in re.finditer(r"box-shadow\s*:\s*(?!none\b)([^;}{]+)", text, re.I)
    ]
    radius_lines = [
        line_number(text, m.start())
        for m in re.finditer(r"border-radius\s*:\s*([^;}{]+)", text, re.I)
    ]
    if card_count >= 4 and len(shadow_lines) >= 4:
        line = shadow_lines[0]
        add_finding(
            findings,
            seen,
            rule="container.card-chrome",
            pass_name="containers",
            severity="medium",
            message=f"Repeated card chrome: {card_count} card-like elements and {len(shadow_lines)} shadows.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Remove shadows/backgrounds first; group with spacing and one hairline. Keep a boundary only for grouping, elevation, or interaction.",
        )
    if re.search(r"backdrop-filter\s*:", text, re.I):
        match = re.search(r"backdrop-filter\s*:", text, re.I)
        assert match is not None
        line = line_number(text, match.start())
        add_finding(
            findings,
            seen,
            rule="container.glass",
            pass_name="containers",
            severity="low",
            message="Glass/blur surface detected; verify it communicates hierarchy rather than decoration.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Remove the blur if a flat surface or spacing can do the job; keep it only for real overlays or depth.",
        )
    if len(radius_lines) >= 8 and card_count >= 6:
        line = radius_lines[0]
        add_finding(
            findings,
            seen,
            rule="container.rounded-repetition",
            pass_name="containers",
            severity="low",
            message="Many rounded containers detected; check whether every block needs its own box.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Collapse to one radius scale and remove containers that only repeat the same shape.",
        )


def scan_colors(
    text: str,
    rel: str,
    findings: list[Finding],
    seen: set[tuple[str, int, str]],
) -> None:
    color_matches = list(
        re.finditer(
            r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)",
            text,
            re.I,
        )
    )
    colors = unique_preserving_order([m.group(0).lower().replace(" ", "") for m in color_matches])
    if len(colors) > 10:
        line = line_number(text, color_matches[0].start())
        add_finding(
            findings,
            seen,
            rule="color.palette-sprawl",
            pass_name="color",
            severity="medium" if len(colors) <= 16 else "high",
            message=f"{len(colors)} unique color literals found; verify each has a role.",
            path=rel,
            line=line,
            evidence=", ".join(colors[:8]),
            repair="Assign canvas/text/muted/accent/state roles, merge near-duplicates, and delete decorative colors.",
        )
    gradients = list(re.finditer(r"(?:linear|radial|conic)-gradient\(", text, re.I))
    if len(gradients) > 2:
        line = line_number(text, gradients[0].start())
        add_finding(
            findings,
            seen,
            rule="color.gradient-overload",
            pass_name="color",
            severity="medium",
            message=f"{len(gradients)} gradients found; check whether they share one material/light concept.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Keep gradients only where they clarify material, depth, or state; remove decorative gradients behind text.",
        )


def scan_type(
    text: str,
    rel: str,
    findings: list[Finding],
    seen: set[tuple[str, int, str]],
) -> None:
    sizes: list[tuple[float, int, str]] = []
    for match in re.finditer(r"font-size\s*:\s*([^;}{]+)", text, re.I):
        raw = match.group(1).strip()
        number = re.search(r"(\d+(?:\.\d+)?)\s*(px|rem)", raw, re.I)
        if not number:
            continue
        value = float(number.group(1))
        if number.group(2).lower() == "rem":
            value *= 16
        if value <= 0:
            continue
        sizes.append((value, line_number(text, match.start()), raw))
    unique_sizes = sorted({round(value, 1) for value, _, _ in sizes})
    if len(unique_sizes) > 4:
        line = sizes[0][1]
        add_finding(
            findings,
            seen,
            rule="type.scale-sprawl",
            pass_name="type",
            severity="medium" if len(unique_sizes) <= 6 else "high",
            message=f"{len(unique_sizes)} font sizes found; collapse to 3–4 functional sizes.",
            path=rel,
            line=line,
            evidence=", ".join(f"{value:g}px" for value in unique_sizes[:10]),
            repair="Choose a small type scale and use weight, spacing, and color for hierarchy instead of one-off sizes.",
        )
    tiny = [(value, line, raw) for value, line, raw in sizes if value < 12]
    if tiny:
        value, line, _ = min(tiny, key=lambda item: item[0])
        add_finding(
            findings,
            seen,
            rule="type.tiny-text",
            pass_name="type",
            severity="high" if value < 10 else "medium",
            message=f"Font size below 12px detected (smallest: {value:g}px).",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Raise to a readable size at the final viewport; if it must stay small, prove it is non-essential metadata.",
        )
    weights = []
    for match in re.finditer(r"font-weight\s*:\s*(\d{3}|bold|normal)", text, re.I):
        weights.append(match.group(1).lower())
    unique_weights = set(weights)
    if len(unique_weights) > 3:
        match = re.search(r"font-weight\s*:", text, re.I)
        assert match is not None
        line = line_number(text, match.start())
        add_finding(
            findings,
            seen,
            rule="type.weight-sprawl",
            pass_name="type",
            severity="low",
            message=f"{len(unique_weights)} font weights found; hierarchy may be over-differentiated.",
            path=rel,
            line=line,
            evidence=", ".join(sorted(unique_weights)),
            repair="Use 2–3 weights and let size/spacing carry the rest.",
        )
    hairline = re.search(r"border(?:-width)?\s*:\s*0?\.5px", text, re.I)
    if hairline:
        line = line_number(text, hairline.start())
        add_finding(
            findings,
            seen,
            rule="type.hairline",
            pass_name="type",
            severity="low",
            message="0.5px border detected; it may disappear at normal pixel density.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Use 1px or a background/divider that survives the final display.",
        )


def scan_focus(
    text: str,
    rel: str,
    findings: list[Finding],
    seen: set[tuple[str, int, str]],
) -> None:
    if rel.lower().endswith((".html", ".htm", ".vue", ".svelte", ".astro")):
        h1_matches = list(re.finditer(r"<h1\b", text, re.I))
        if len(h1_matches) > 1:
            line = line_number(text, h1_matches[0].start())
            add_finding(
                findings,
                seen,
                rule="focus.multiple-h1",
                pass_name="focus",
                severity="low",
                message=f"{len(h1_matches)} h1 elements found; confirm the page still has one clear primary message.",
                path=rel,
                line=line,
                evidence=line_evidence(text, line),
                repair="Keep one page-level h1 and use h2/h3 for sections.",
            )
        primary = re.findall(
            r"class(?:Name)?\s*=\s*[\"'][^\"']*(?:btn-primary|button-primary|cta-primary|primary-action|button--primary)[^\"']*[\"']",
            text,
            re.I,
        )
        if len(primary) >= 3:
            match = re.search(
                r"class(?:Name)?\s*=\s*[\"'][^\"']*(?:btn-primary|button-primary|cta-primary|primary-action|button--primary)[^\"']*[\"']",
                text,
                re.I,
            )
            assert match is not None
            line = line_number(text, match.start())
            add_finding(
                findings,
                seen,
                rule="focus.competing-primary-actions",
                pass_name="focus",
                severity="medium",
                message=f"{len(primary)} primary actions found; the page may lack a single focus.",
                path=rel,
                line=line,
                evidence=line_evidence(text, line),
                repair="Choose one primary action; demote the rest to secondary/text links or move them later.",
            )
        sections = len(re.findall(r"<section\b", text, re.I))
        h2_count = len(re.findall(r"<h2\b", text, re.I))
        if sections >= 8 and h2_count >= 8:
            line = line_number(text, re.search(r"<section\b", text, re.I).start())  # type: ignore[union-attr]
            add_finding(
                findings,
                seen,
                rule="focus.section-density",
                pass_name="focus",
                severity="low",
                message=f"{sections} sections and {h2_count} section headings; check that each viewport has one focus.",
                path=rel,
                line=line,
                evidence=line_evidence(text, line),
                repair="Group or defer sections; do not give every block equal visual weight.",
            )


def scan_motion(
    text: str,
    rel: str,
    findings: list[Finding],
    seen: set[tuple[str, int, str]],
) -> None:
    transition_all = re.search(
        r"(?:\.style\.)?transition(?:-property)?\s*(?::|=)\s*['\"]?all\b",
        text,
        re.I,
    )
    if transition_all:
        line = line_number(text, transition_all.start())
        add_finding(
            findings,
            seen,
            rule="motion.transition-all",
            pass_name="motion",
            severity="medium",
            message="`transition: all` detected; it hides which properties animate and often creates accidental motion.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="List only the properties that should animate, usually color, opacity, transform, or a specific dimension.",
        )

    infinite_matches = list(
        re.finditer(
            r"(?:\.style\.)?animation(?:-iteration-count)?\s*(?::|=)\s*[^;{}\n]*\binfinite\b",
            text,
            re.I,
        )
    )
    has_reduced_motion = bool(re.search(r"prefers-reduced-motion", text, re.I))
    animation_matches = list(
        re.finditer(
            r"(?<![\w-])(?:\.style\.)?animation(?:-name)?\s*(?::|=)\s*[^;{}\n]+",
            text,
            re.I,
        )
    )
    animations = [
        match.group(0)
        for match in animation_matches
        if not re.search(r"(?::|=)\s*['\"]?none\b", match.group(0), re.I)
    ]
    if infinite_matches and not has_reduced_motion:
        line = line_number(text, infinite_matches[0].start())
        add_finding(
            findings,
            seen,
            rule="motion.ambient-without-reduced",
            pass_name="motion",
            severity="high",
            message="Infinite animation found without a `prefers-reduced-motion` branch.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Remove the loop or add a reduced-motion branch that stops ambient motion while keeping necessary feedback.",
        )
    elif animations and not has_reduced_motion:
        line = line_number(text, animation_matches[0].start())
        add_finding(
            findings,
            seen,
            rule="motion.no-reduced-motion",
            pass_name="motion",
            severity="medium",
            message="Animation is present but no `prefers-reduced-motion` branch was found.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Add a reduced-motion branch; keep essential state feedback and stop decorative movement.",
        )

    keyframe_names = re.findall(r"@keyframes\s+([A-Za-z0-9_-]+)", text)
    ambient_names = [
        name
        for name in keyframe_names
        if re.search(r"(?:float|bounce|pulse|wiggle|breathe|drift|spin|blob)", name, re.I)
    ]
    if ambient_names:
        match = re.search(r"@keyframes\s+" + re.escape(ambient_names[0]), text)
        assert match is not None
        line = line_number(text, match.start())
        add_finding(
            findings,
            seen,
            rule="motion.ambient-keyframes",
            pass_name="motion",
            severity="medium",
            message="Ambient/loop-style keyframes found; confirm they carry meaning.",
            path=rel,
            line=line,
            evidence=", ".join(ambient_names[:6]),
            repair="Remove decorative float/bounce/pulse; if the motion expresses an ongoing state, keep it slow, low-contrast, and disable it under reduced motion.",
        )

    durations: list[tuple[float, int]] = []
    duration_re = re.compile(
        r"(?:\.style\.)?(?:transition|animation)(?:-duration)?\s*(?::|=)\s*([^;}{'\"]+)",
        re.I,
    )
    for match in duration_re.finditer(text):
        for duration in re.finditer(r"(\d+(?:\.\d+)?)(ms|s)\b", match.group(1), re.I):
            value = float(duration.group(1))
            if duration.group(2).lower() == "s":
                value *= 1000
            if value >= 10:
                durations.append((value, line_number(text, match.start())))
    if len(durations) >= 4:
        values = [value for value, _ in durations]
        unique_values = set(round(value, 1) for value in values)
        most_common = max(unique_values, key=lambda value: values.count(value))
        share = values.count(most_common) / len(values)
        if len(unique_values) == 1 or (len(durations) >= 6 and share >= 0.8):
            line = durations[0][1]
            add_finding(
                findings,
                seen,
                rule="motion.uniform-duration",
                pass_name="motion",
                severity="medium",
                message=f"{len(durations)} motion durations are dominated by {most_common:g}ms.",
                path=rel,
                line=line,
                evidence=f"dominant {most_common:g}ms in {values.count(most_common)}/{len(values)} declarations",
                repair="Split durations by job: fast feedback, short state change, longer reveal/scene transition. Vary by distance and weight.",
            )

    smooth_scroll = re.search(r"scroll-behavior\s*:\s*smooth", text, re.I)
    if smooth_scroll:
        line = line_number(text, smooth_scroll.start())
        add_finding(
            findings,
            seen,
            rule="motion.smooth-scroll",
            pass_name="motion",
            severity="low",
            message="Smooth scrolling forced globally; check motion sensitivity and reduced-motion behavior.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Use `scroll-behavior: auto` by default and respect `prefers-reduced-motion`.",
        )

    outline_none = re.search(r"outline\s*:\s*(?:none|0)\b", text, re.I)
    if outline_none and not re.search(r":focus-visible\b|:focus\b", text, re.I):
        line = line_number(text, outline_none.start())
        add_finding(
            findings,
            seen,
            rule="motion.focus-suppressed",
            pass_name="motion",
            severity="medium",
            message="Outline removed without an obvious focus replacement.",
            path=rel,
            line=line,
            evidence=line_evidence(text, line),
            repair="Add a visible `:focus-visible` style; never remove focus indication without an equivalent.",
        )


def scan_file(
    path: Path,
    rel: str,
    text: str,
    findings: list[Finding],
    seen: set[tuple[str, int, str]],
) -> None:
    scan_copy(text, rel, findings, seen)
    scan_containers(text, rel, findings, seen)
    scan_colors(text, rel, findings, seen)
    scan_type(text, rel, findings, seen)
    scan_focus(text, rel, findings, seen)
    scan_motion(text, rel, findings, seen)


def build_report(findings: list[Finding], files: list[str], targets: list[str], notes: list[str], truncated: int) -> dict:
    summary = {"high": 0, "medium": 0, "low": 0}
    for finding in findings:
        summary[finding.severity] += 1
    sorted_findings = sorted(
        findings,
        key=lambda item: (
            -SEVERITY_RANK[item.severity],
            PASS_ORDER.index(item.pass_name) if item.pass_name in PASS_ORDER else 99,
            item.path,
            item.line,
            item.rule,
        ),
    )
    return {
        "tool": "de-ai-visual-review/audit_visual_code.py",
        "version": TOOL_VERSION,
        "targets": targets,
        "files_scanned": files,
        "summary": {**summary, "total": len(findings)},
        "findings": [finding.as_dict() for finding in sorted_findings],
        "truncated": truncated,
        "notes": notes,
        "manual_checks": MANUAL_CHECKS,
        "disclaimer": "Heuristic candidates only. Confirm against rendered output; this tool does not render, measure contrast, or judge motion meaning.",
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Visual AI-smell scan",
        "",
        f"- Targets: {', '.join(report['targets'])}",
        f"- Files scanned: {len(report['files_scanned'])}",
        f"- Candidates: **{summary['total']}** (high {summary['high']} / medium {summary['medium']} / low {summary['low']})",
        "- Heuristic only: confirm every item against the rendered result.",
        "",
    ]
    if report["notes"]:
        lines.append("Notes:")
        lines.extend(f"- {note}" for note in report["notes"])
        lines.append("")
    if report["findings"]:
        lines.extend(
            [
                "| Severity | Pass | Evidence | Candidate finding | Repair direction |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for finding in report["findings"]:
            location = f"{finding['path']}:{finding['line']}"
            evidence = finding["evidence"].replace("|", "\\|")
            message = finding["message"].replace("|", "\\|")
            repair = finding["repair"].replace("|", "\\|")
            lines.append(
                f"| {finding['severity']} | {finding['pass']} | `{location}`<br>{evidence} | {message} | {repair} |"
            )
        if report["truncated"]:
            lines.append("")
            lines.append(f"_{report['truncated']} additional candidates omitted by `--max-findings`._")
    else:
        lines.append("No heuristic candidates found. This does not prove the UI is clean; run the manual checks below.")
    lines.extend(["", "## Manual checks the scan cannot decide", ""])
    lines.extend(f"- [ ] {item}" for item in report["manual_checks"])
    lines.extend(["", report["disclaimer"], ""])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find candidate AI-generated visual signals in HTML/CSS/JS source. Heuristic only."
    )
    parser.add_argument("targets", nargs="+", help="Files or directories to scan.")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--max-findings",
        type=int,
        default=40,
        help="Maximum findings to print (default: 40).",
    )
    parser.add_argument(
        "--fail-on",
        choices=("none", "high", "medium", "low"),
        default="none",
        help="Return exit code 2 when a finding at or above this severity exists.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        files, notes, bases = iter_source_files(args.targets)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not files:
        print("error: no supported source files found in the given targets", file=sys.stderr)
        return 2

    findings: list[Finding] = []
    seen: set[tuple[str, int, str]] = set()
    scanned: list[str] = []
    for path in files:
        rel = display_path(path, bases)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            notes.append(f"Could not read {rel}: {exc}")
            continue
        scanned.append(rel)
        scan_file(path, rel, text, findings, seen)

    truncated = max(0, len(findings) - max(0, args.max_findings))
    if args.max_findings >= 0:
        findings = findings[: args.max_findings]
    report = build_report(findings, scanned, args.targets, notes, truncated)

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report))

    if args.fail_on != "none":
        threshold = SEVERITY_RANK[args.fail_on]
        if any(SEVERITY_RANK[finding["severity"]] >= threshold for finding in report["findings"]):
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
