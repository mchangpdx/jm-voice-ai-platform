"""Vertical Template Framework — 9-layer loader + validator.
(9-layer 템플릿 로더 + 검증기 — Phase 1.3)

This module loads a vertical's nine yaml/text layers into a single
`VerticalTemplate` TypedDict and emits non-blocking `ValidationIssue`
records for missing files, parse errors, and missing required fields.

Lenient by design: missing files do not raise. Callers must tolerate
`None` for any layer. This keeps incremental migration safe — a vertical
can ship the 4 historical files first and add `intake_flow.yaml` later
without crashing.

Authoritative spec: `backend/app/templates/_base/spec.md`.
Kind map:           `backend/app/templates/_base/vertical_kinds.yaml`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, TypedDict

import yaml

log = logging.getLogger(__name__)

# `<repo>/backend/app/templates/` — siblings of this file's parent.
# (templates 디렉터리 — 이 파일의 상위 디렉터리)
_TEMPLATES_DIR = Path(__file__).resolve().parents[1]
_BASE_DIR      = _TEMPLATES_DIR / "_base"

# Layer 1-4 keep their historical filenames; 5-9 are new.
# Order here drives the load sequence in `load_template`.
LAYER_FILES: dict[str, str] = {
    "safety_rules":    "allergen_rules.yaml",
    "catalog":         "menu.yaml",
    "option_groups":   "modifier_groups.yaml",
    "persona_prompt":  "system_prompt_base.txt",   # plain text, not yaml
    "intake_flow":     "intake_flow.yaml",
    "scheduler":       "scheduler.yaml",
    "emergency_rules": "emergency_rules.yaml",
    "crm_followup":    "crm_followup.yaml",
    "pricing_policy":  "pricing_policy.yaml",
}

VerticalKind = Literal["order", "service", "service_with_dispatch"]


# ── Issue records ────────────────────────────────────────────────────────────


@dataclass
class ValidationIssue:
    """One validation finding — never raised, always collected.
    (검증 발견 사항 — 절대 raise 안 함, 수집만)
    """
    severity: Literal["warn", "error"]
    layer:    str
    path:     str       # dotted path within the layer, e.g. "phases[2].requires"
    message:  str


# ── Result TypedDict ─────────────────────────────────────────────────────────


class VerticalTemplate(TypedDict, total=False):
    """All nine layers + metadata for one vertical.
    (한 vertical의 9-layer 전체 + 메타데이터)

    `total=False` — every key is optional because Lenient loading may
    return None for any layer that has no file or fails to parse.
    """
    vertical:        str
    kind:            VerticalKind | None
    persona_name:    str | None
    multilingual:    list[str]
    safety_rules:    dict | None
    catalog:         dict | None
    option_groups:   dict | None
    persona_prompt:  str  | None
    intake_flow:     dict | None
    scheduler:       dict | None
    emergency_rules: dict | None
    crm_followup:    dict | None
    pricing_policy:  dict | None
    issues:          list[ValidationIssue]


# ── Loading ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _load_vertical_kinds() -> dict[str, Any]:
    """Read `_base/vertical_kinds.yaml` once and cache.
    (vertical_kinds.yaml 1회 read + cache)
    """
    path = _BASE_DIR / "vertical_kinds.yaml"
    if not path.is_file():
        log.warning("vertical_kinds.yaml missing at %s", path)
        return {"kinds": {}, "verticals": {}}
    try:
        with path.open("r") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        log.warning("vertical_kinds.yaml parse failed: %s", exc)
        return {"kinds": {}, "verticals": {}}
    data.setdefault("kinds", {})
    data.setdefault("verticals", {})
    return data


def _resolve_kind_and_meta(vertical: str) -> tuple[VerticalKind | None, str | None, list[str]]:
    """Look up `(kind, persona_name, multilingual)` from `vertical_kinds.yaml`.
    Returns `(None, None, [])` when the vertical isn't registered.
    (vertical → kind/persona/multilingual 룩업, 미등록 시 None tuple)
    """
    data = _load_vertical_kinds()
    entry = (data.get("verticals") or {}).get(vertical)
    if not isinstance(entry, dict):
        return None, None, []
    kind = entry.get("kind") if entry.get("kind") in ("order", "service", "service_with_dispatch") else None
    persona = entry.get("persona_name")
    languages = entry.get("multilingual") or []
    if not isinstance(languages, list):
        languages = []
    return kind, persona, languages


def _load_one(path: Path) -> tuple[Any, ValidationIssue | None]:
    """Load one yaml or txt file. Missing → (None, None) silently.
    Parse error → (None, warn-issue).
    (yaml/txt 1건 로드 — 누락은 silently None, parse error만 issue)
    """
    if not path.is_file():
        return None, None
    try:
        if path.suffix == ".txt":
            return path.read_text(encoding="utf-8"), None
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f), None
    except (yaml.YAMLError, OSError) as exc:
        return None, ValidationIssue(
            severity="warn",
            layer=path.stem,
            path="<file>",
            message=f"parse failed: {exc}",
        )


def load_template(vertical: str) -> VerticalTemplate:
    """Load all 9 layers for a vertical + kind metadata.
    Never raises. Missing layers are returned as None.
    (vertical의 9 layer 전체 + kind 메타 — 누락은 None, 절대 raise 안 함)
    """
    vertical = (vertical or "").strip().lower()
    issues: list[ValidationIssue] = []

    kind, persona_name, multilingual = _resolve_kind_and_meta(vertical)
    if kind is None:
        issues.append(ValidationIssue(
            severity="warn",
            layer="_meta",
            path="vertical_kinds.verticals",
            message=f"vertical '{vertical}' not registered in vertical_kinds.yaml",
        ))

    template: VerticalTemplate = {
        "vertical":     vertical,
        "kind":         kind,
        "persona_name": persona_name,
        "multilingual": multilingual,
        "issues":       issues,
    }

    vertical_dir = _TEMPLATES_DIR / vertical
    for layer_key, filename in LAYER_FILES.items():
        value, issue = _load_one(vertical_dir / filename)
        template[layer_key] = value  # type: ignore[literal-required]
        if issue is not None:
            # Re-label issue with the conceptual layer name.
            issue.layer = layer_key
            issues.append(issue)

    # Layer-specific validation (lenient — warns only).
    _validate_safety_rules(template, issues)
    _validate_catalog(template, issues)
    _validate_intake_flow(template, issues)
    _validate_scheduler(template, issues)

    return template


# ── Layer-specific validators (lenient) ──────────────────────────────────────
# Each helper appends to `issues` and never raises. Severity is `warn`
# unless a structural problem would make the layer unusable.
# (모두 lenient — issues에 append만, raise 없음)


def _validate_safety_rules(template: VerticalTemplate, issues: list[ValidationIssue]) -> None:
    rules = template.get("safety_rules")
    if rules is None:
        return
    if not isinstance(rules, dict):
        issues.append(ValidationIssue(
            "error", "safety_rules", "<root>", "top-level must be a mapping"))
        return
    patterns = rules.get("patterns") or []
    if not isinstance(patterns, list):
        issues.append(ValidationIssue(
            "error", "safety_rules", "patterns", "must be a list"))
        return
    for idx, pat in enumerate(patterns):
        if not isinstance(pat, dict):
            issues.append(ValidationIssue(
                "warn", "safety_rules", f"patterns[{idx}]", "entry is not a mapping"))
            continue
        if not pat.get("keywords"):
            issues.append(ValidationIssue(
                "warn", "safety_rules", f"patterns[{idx}].keywords", "missing or empty"))
        # spec.md §3 — confidence ≥ 0.90 should explain why.
        conf = pat.get("confidence")
        if isinstance(conf, (int, float)) and conf >= 0.90 and not pat.get("reason"):
            issues.append(ValidationIssue(
                "warn", "safety_rules", f"patterns[{idx}].reason",
                "high-confidence rule (≥0.90) should have a reason"))


def _validate_catalog(template: VerticalTemplate, issues: list[ValidationIssue]) -> None:
    catalog = template.get("catalog")
    if catalog is None:
        return
    if not isinstance(catalog, dict):
        issues.append(ValidationIssue(
            "error", "catalog", "<root>", "top-level must be a mapping"))
        return
    categories = catalog.get("categories") or []
    if not isinstance(categories, list):
        issues.append(ValidationIssue(
            "error", "catalog", "categories", "must be a list"))
        return

    needs_duration = template.get("kind") in ("service", "service_with_dispatch")
    for ci, cat in enumerate(categories):
        if not isinstance(cat, dict):
            continue
        for ii, item in enumerate(cat.get("items") or []):
            if not isinstance(item, dict):
                continue
            base = f"categories[{ci}].items[{ii}]"
            for req in ("id", "en", "price"):
                if item.get(req) is None:
                    issues.append(ValidationIssue(
                        "warn", "catalog", f"{base}.{req}", "missing"))
            if needs_duration and item.get("duration_min") is None:
                issues.append(ValidationIssue(
                    "warn", "catalog", f"{base}.duration_min",
                    "service-kind verticals should specify duration_min"))


def _validate_intake_flow(template: VerticalTemplate, issues: list[ValidationIssue]) -> None:
    flow = template.get("intake_flow")
    if flow is None:
        return
    if not isinstance(flow, dict):
        issues.append(ValidationIssue(
            "error", "intake_flow", "<root>", "top-level must be a mapping"))
        return
    phases = flow.get("phases") or []
    if not isinstance(phases, list) or not phases:
        issues.append(ValidationIssue(
            "warn", "intake_flow", "phases", "should be a non-empty list"))
        return
    for idx, phase in enumerate(phases):
        if not isinstance(phase, dict):
            continue
        if not phase.get("id"):
            issues.append(ValidationIssue(
                "warn", "intake_flow", f"phases[{idx}].id", "missing"))


def _validate_scheduler(template: VerticalTemplate, issues: list[ValidationIssue]) -> None:
    sched = template.get("scheduler")
    if sched is None:
        return
    if not isinstance(sched, dict):
        issues.append(ValidationIssue(
            "error", "scheduler", "<root>", "top-level must be a mapping"))
        return
    allowed = {"table", "stylist", "technician", "bay", "none"}
    kind_val = sched.get("slot_kind")
    if kind_val is not None and kind_val not in allowed:
        issues.append(ValidationIssue(
            "warn", "scheduler", "slot_kind",
            f"unknown slot_kind '{kind_val}' (allowed: {sorted(allowed)})"))


# ── Convenience accessors ───────────────────────────────────────────────────


def validate_layer(template: VerticalTemplate, layer: str) -> list[ValidationIssue]:
    """Return only the issues that belong to a given layer.
    (특정 layer에 해당하는 issue만 반환)
    """
    return [i for i in template.get("issues", []) if i.layer == layer]


def has_errors(template: VerticalTemplate) -> bool:
    """True iff any issue has severity 'error'. Used by callers that
    refuse to start a session on hard validation failures.
    (severity=error 1건이라도 있으면 True)
    """
    return any(i.severity == "error" for i in template.get("issues", []))


__all__ = [
    "LAYER_FILES",
    "ValidationIssue",
    "VerticalKind",
    "VerticalTemplate",
    "has_errors",
    "load_template",
    "validate_layer",
]
