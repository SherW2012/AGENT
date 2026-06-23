from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .project_tools import MAX_READ_BYTES, resolve_inside


DIRECT_IDENTIFIER_KEYS = {
    "accession_number",
    "address",
    "birth_date",
    "date_of_birth",
    "medical_record_number",
    "mrn",
    "patient_id",
    "patient_name",
    "phone",
}


def _load_snapshot(root: Path, path: str) -> tuple[Path, dict[str, Any]]:
    target = resolve_inside(root, path)
    if not target.is_file() or target.suffix.lower() != ".json":
        raise ValueError("计划快照必须是工程目录内的 JSON 文件")
    if target.stat().st_size > MAX_READ_BYTES:
        raise ValueError("计划快照超过 1 MB 上限")
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("计划快照根节点必须是对象")
    return target, data


def _find_identifier_keys(value: Any, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            if str(key).lower() in DIRECT_IDENTIFIER_KEYS:
                found.append(child_path)
            found.extend(_find_identifier_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_identifier_keys(child, f"{prefix}[{index}]"))
    return found


def validate_plan_snapshot(root: Path, path: str) -> dict[str, Any]:
    target, data = _load_snapshot(root, path)
    errors: list[str] = []
    warnings: list[str] = []

    identifiers = _find_identifier_keys(data)
    if identifiers:
        errors.append("发现直接标识符字段，拒绝处理: " + ", ".join(identifiers[:10]))
    if data.get("deidentified") is not True:
        errors.append("deidentified 必须显式为 true")
    if not isinstance(data.get("case_id"), str) or not data.get("case_id"):
        errors.append("缺少非空 case_id")
    if not isinstance(data.get("source"), dict):
        errors.append("缺少 source 对象（应记录 TPS/算法版本）")

    metrics = data.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        errors.append("metrics 必须是非空数组")
    else:
        for index, metric in enumerate(metrics):
            location = f"metrics[{index}]"
            if not isinstance(metric, dict):
                errors.append(f"{location} 必须是对象")
                continue
            if not all(metric.get(key) for key in ("structure", "name", "unit")):
                errors.append(f"{location} 缺少 structure/name/unit")
            value = metric.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                errors.append(f"{location}.value 必须是有限数值")
            elif value < 0:
                warnings.append(f"{location}.value 为负，请核对该指标定义")

    return {
        "path": target.relative_to(root).as_posix(),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "disclaimer": "仅验证数据结构与基本数值，不判断临床可接受性。",
    }


def summarize_plan_snapshot(root: Path, path: str) -> dict[str, Any]:
    validation = validate_plan_snapshot(root, path)
    if not validation["valid"]:
        return {**validation, "metrics": []}
    target, data = _load_snapshot(root, path)
    source = data["source"]
    safe_source = {
        key: source.get(key)
        for key in ("tps_name", "tps_version", "algorithm", "algorithm_version", "exported_at")
        if source.get(key) is not None
    }
    metrics = [
        {
            "structure": item["structure"],
            "name": item["name"],
            "value": item["value"],
            "unit": item["unit"],
        }
        for item in data["metrics"]
    ]
    return {
        "path": target.relative_to(root).as_posix(),
        "case_id": data["case_id"],
        "source": safe_source,
        "metrics": metrics,
        "metric_count": len(metrics),
        "disclaimer": "指标为源快照原值，未经 Agent 重算，不构成临床结论。",
    }

