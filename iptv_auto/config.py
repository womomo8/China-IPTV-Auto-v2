"""Load and validate the single source of truth configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG = Path("config.yaml")


class ConfigError(ValueError):
    """Raised when the project configuration is invalid."""


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"配置文件不存在：{config_path}")
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件格式错误：{exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("配置文件顶层必须是 YAML 对象")

    weights = data.get("scoring", {}).get("weights", {})
    expected = {
        "success_rate": 30,
        "stability": 25,
        "throughput": 15,
        "freshness": 15,
        "ad_placeholder_risk": 10,
        "source_reliability": 5,
    }
    if weights != expected:
        raise ConfigError(f"评分权重必须保持蓝图规定值：{expected}")
    if sum(weights.values()) != 100:
        raise ConfigError("评分权重总和必须为100")

    release = data.get("release", {})
    if release.get("minimum_success_rate") != 0.90:
        raise ConfigError("正式发布成功率门槛必须为90%")
    if release.get("minimum_score") != 70:
        raise ConfigError("正式发布评分门槛必须为70")
    if release.get("max_lines_per_channel") != 3:
        raise ConfigError("每频道正式发布上限必须为3条")
    if data.get("measurement", {}).get("deep_candidates_per_channel") != 5:
        raise ConfigError("每频道深入检测上限必须为5条")
    return data
