
"""Load and validate the single official channel catalog."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml


class ChannelCatalogError(ValueError):
    """Raised when the official channel catalog is invalid."""


def _normalize_name(value: str) -> str:
    """Normalize harmless spacing and punctuation without losing '+'."""
    text = str(value or "").strip().casefold()
    return re.sub(r"[\s\-_.·]+", "", text)


@dataclass(frozen=True)
class OfficialChannel:
    channel_id: str
    category: str
    name: str


class ChannelCatalog:
    """Immutable lookup table for the official channels."""

    def __init__(self, channels: list[OfficialChannel]):
        self.channels = tuple(channels)
        self._by_name: dict[str, OfficialChannel] = {}

        for channel in channels:
            key = _normalize_name(channel.name)
            if not key:
                raise ChannelCatalogError("正式频道名称不能为空")
            if key in self._by_name:
                raise ChannelCatalogError(
                    f"正式频道名称重复或归一化后冲突：{channel.name}"
                )
            self._by_name[key] = channel

        # Explicit aliases for common CCTV naming variations.
        aliases = {
            "CCTV4": "CCTV-4 中文国际",
            "CCTV4中文国际": "CCTV-4 中文国际",
        }

        for alias, official_name in aliases.items():
            target = self._by_name.get(_normalize_name(official_name))
            if target is None:
                raise ChannelCatalogError(
                    f"频道别名对应的正式频道不存在：{official_name}"
                )
            alias_key = _normalize_name(alias)
            existing = self._by_name.get(alias_key)
            if existing is not None and existing != target:
                raise ChannelCatalogError(
                    f"频道别名发生冲突：{alias}"
                )
            self._by_name[alias_key] = target

    def resolve(self, name: str) -> OfficialChannel | None:
        """Return the official channel, or None for an unknown channel."""
        return self._by_name.get(_normalize_name(name))

    def contains_official(self, name: str, category: str) -> bool:
        """Check that both name and category exactly match the catalog."""
        channel = self.resolve(name)
        return bool(
            channel
            and channel.name == name
            and channel.category == category
        )

    @property
    def total_channels(self) -> int:
        return len(self.channels)


def load_channel_catalog(path: str | Path) -> ChannelCatalog:
    """Read and strictly validate config/channels.yaml."""
    catalog_path = Path(path)

    if not catalog_path.is_file():
        raise ChannelCatalogError(
            f"正式频道目录文件不存在：{catalog_path}"
        )

    try:
        data: Any = yaml.safe_load(
            catalog_path.read_text(encoding="utf-8")
        )
    except yaml.YAMLError as exc:
        raise ChannelCatalogError(
            f"正式频道目录 YAML 格式错误：{exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ChannelCatalogError("正式频道目录顶层必须是对象")

    if data.get("total_channels") != 38:
        raise ChannelCatalogError(
            "正式频道目录 total_channels 必须为 38"
        )

    categories = data.get("categories")
    if not isinstance(categories, list):
        raise ChannelCatalogError("正式频道目录 categories 必须是列表")

    channels: list[OfficialChannel] = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    actual_total = 0

    for category_item in categories:
        if not isinstance(category_item, dict):
            raise ChannelCatalogError("频道分类项目必须是对象")

        category_id = category_item.get("id")
        category_name = category_item.get("name")
        expected_count = category_item.get("expected_count")
        names = category_item.get("channels")

        if not isinstance(category_id, str) or not category_id.strip():
            raise ChannelCatalogError("频道分类 id 必须是非空文本")

        if not isinstance(category_name, str) or not category_name.strip():
            raise ChannelCatalogError("频道分类 name 必须是非空文本")

        if type(expected_count) is not int or expected_count <= 0:
            raise ChannelCatalogError(
                f"{category_name} expected_count 必须是正整数"
            )

        if not isinstance(names, list):
            raise ChannelCatalogError(
                f"{category_name} 的 channels 必须是列表"
            )

        if len(names) != expected_count:
            raise ChannelCatalogError(
                f"{category_name} 数量不符："
                f"目录标注 {expected_count} 个，实际 {len(names)} 个"
            )

        for name in names:
            if not isinstance(name, str) or not name.strip():
                raise ChannelCatalogError(
                    f"{category_name} 存在空频道名称"
                )

            clean_name = name.strip()
            normalized = _normalize_name(clean_name)

            if normalized in seen_names:
                raise ChannelCatalogError(
                    f"正式频道重复：{clean_name}"
                )

            seen_names.add(normalized)

            # Keep the existing stable_channel_id algorithm unchanged.
            from .identity import stable_channel_id

            channel_id = stable_channel_id(
                category_name.strip(),
                clean_name,
            )

            if channel_id in seen_ids:
                raise ChannelCatalogError(
                    f"正式频道 ID 冲突：{clean_name}"
                )

            seen_ids.add(channel_id)
            channels.append(
                OfficialChannel(
                    channel_id=channel_id,
                    category=category_name.strip(),
                    name=clean_name,
                )
            )
            actual_total += 1

    if actual_total != 38:
        raise ChannelCatalogError(
            f"正式频道总数错误：应为 38，实际为 {actual_total}"
        )

    return ChannelCatalog(channels)
