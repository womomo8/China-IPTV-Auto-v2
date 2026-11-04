
"""Load and strictly validate the single source of truth configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml


DEFAULT_CONFIG = Path("config.yaml")

EXPECTED_WEIGHTS = {
    "success_rate": 30,
    "stability": 25,
    "throughput": 15,
    "freshness": 15,
    "ad_placeholder_risk": 10,
    "source_reliability": 5,
}
EXPECTED_GRADES = {"A": 85, "B": 70, "C": 50}


class ConfigError(ValueError):
    """Raised when the project configuration is invalid."""


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"配置项 {name} 必须是 YAML 对象，不能缺失、为 null 或使用其他类型")
    return value


def _exact_value(section: dict[str, Any], key: str, expected: Any, label: str) -> None:
    actual = section.get(key)
    # Exact type check prevents True from being accepted as integer 1.
    if type(actual) is not type(expected) or actual != expected:
        raise ConfigError(f"{label}必须为 {expected!r}，当前为 {actual!r}")


def _positive_number(section: dict[str, Any], key: str, label: str, *, maximum: float | None = None) -> None:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{label}必须是大于 0 的数字")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{label}不能超过 {maximum}")


def _positive_int(section: dict[str, Any], key: str, label: str, *, maximum: int | None = None) -> None:
    value = section.get(key)
    if type(value) is not int or value <= 0:
        raise ConfigError(f"{label}必须是大于 0 的整数")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{label}不能超过 {maximum}")


def _validate_manual_sources(value: Any) -> None:
    if not isinstance(value, list):
        raise ConfigError("sources.manual 必须是列表")
    seen_urls: set[str] = set()
    for index, item in enumerate(value):
        label = f"sources.manual 第 {index + 1} 项"
        if not isinstance(item, dict):
            raise ConfigError(f"{label}必须是对象")
        name = item.get("name")
        url = item.get("url")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"{label}的 name 必须是非空文本")
        if not isinstance(url, str) or not url.strip():
            raise ConfigError(f"{label}的 url 必须是非空文本")
        parsed = urlsplit(url.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"{label}的 url 必须是有效的 HTTP/HTTPS 订阅地址")
        normalized = url.strip()
        if normalized in seen_urls:
            raise ConfigError(f"sources.manual 存在重复订阅地址：{normalized}")
        seen_urls.add(normalized)


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"配置文件不存在：{config_path}")
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件格式错误：{exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("配置文件顶层必须是 YAML 对象")

    project = _section(data, "project")
    paths = _section(data, "paths")
    sources = _section(data, "sources")
    discovery = _section(data, "discovery")
    precheck = _section(data, "precheck")
    measurement = _section(data, "measurement")
    scoring = _section(data, "scoring")
    release = _section(data, "release")
    network_identity = _section(data, "network_identity")
    blacklist = _section(data, "blacklist")

    if not isinstance(project.get("name"), str) or not project["name"].strip():
        raise ConfigError("project.name 必须是非空文本")
    if not isinstance(project.get("timezone"), str) or not project["timezone"].strip():
        raise ConfigError("project.timezone 必须是非空文本")

    for key in ("database", "output_dir", "playlist", "backup_dir", "logs_dir"):
        value = paths.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"paths.{key} 必须是非空路径文本")

    _exact_value(sources, "pool_capacity", 30, "来源池容量")
    _positive_int(sources, "new_sources_per_run", "sources.new_sources_per_run", maximum=30)
    _exact_value(sources, "discovery_enabled", True, "自动发现开关")
    _validate_manual_sources(sources.get("manual"))

    _positive_int(discovery, "max_seconds", "discovery.max_seconds", maximum=3600)
    _positive_number(discovery, "request_timeout_seconds", "discovery.request_timeout_seconds", maximum=120)
    _positive_int(discovery, "max_candidate_lines", "discovery.max_candidate_lines", maximum=10000)

    for key in (
        "require_http_or_https_or_supported_stream_scheme",
        "reject_empty_url",
        "reject_obvious_placeholders",
    ):
        _exact_value(precheck, key, True, f"precheck.{key}")

    _exact_value(measurement, "basic_rounds_required_for_release", 3, "基础测速轮数")
    _positive_number(measurement, "basic_timeout_seconds", "measurement.basic_timeout_seconds", maximum=120)
    _positive_int(measurement, "max_concurrency", "measurement.max_concurrency", maximum=64)
    _exact_value(measurement, "deep_candidates_per_channel", 5, "每频道深入检测候选上限")
    _positive_number(measurement, "deep_timeout_seconds", "measurement.deep_timeout_seconds", maximum=300)

    # The stability module supports at most two retests; keep config aligned.
    _positive_int(measurement, "stability_retests", "measurement.stability_retests", maximum=2)

    weights = scoring.get("weights")
    if not isinstance(weights, dict) or weights != EXPECTED_WEIGHTS:
        raise ConfigError(f"scoring.weights 必须保持蓝图规定值：{EXPECTED_WEIGHTS}")
    if sum(weights.values()) != 100:
        raise ConfigError("评分权重总和必须为 100")
    grades = scoring.get("grades")
    if not isinstance(grades, dict) or grades != EXPECTED_GRADES:
        raise ConfigError(f"scoring.grades 必须保持蓝图规定值：{EXPECTED_GRADES}")

    release_invariants = {
        "minimum_success_rate": 0.90,
        "minimum_score": 70,
        "require_latest_measurement_success": True,
        "require_three_basic_rounds": True,
        "require_ffprobe_pass": True,
        "max_lines_per_channel": 3,
        "preserve_previous_on_failure": True,
        "atomic_replace": True,
    }
    for key, expected in release_invariants.items():
        _exact_value(release, key, expected, f"正式发布门槛 release.{key}")

    _exact_value(network_identity, "cloud_measurements_must_be_labeled", True,
                 "云端检测环境标识要求")
    _exact_value(network_identity, "never_claim_cloud_test_is_fujian_mobile_home_test", True,
                 "禁止将云端检测冒充福建移动家庭实测")
    _exact_value(blacklist, "confirmed_ad_or_invalid_content_only", True,
                 "黑名单确认条件")
    _exact_value(blacklist, "transient_network_errors_are_not_permanent_blacklist", True,
                 "临时网络错误不得永久封禁")
    _exact_value(blacklist, "congestion_or_stutter_only_reduces_score", True,
                 "卡顿仅降低质量评分")

    return data
