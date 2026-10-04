"""Load and lightly validate a business config file."""
from __future__ import annotations

from pathlib import Path

import yaml

from .normalize import CodeMap, NameParser


class Config:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        with open(self.path, encoding="utf-8") as f:
            self.raw = yaml.safe_load(f) or {}
        self.sources: dict = self.raw.get("sources", {})
        if not self.sources:
            raise ValueError(f"{self.path} defines no sources")
        self.code_maps = {name: CodeMap(spec) for name, spec in self.raw.get("value_maps", {}).items()}
        self.names = NameParser(self.raw.get("nicknames", {}))
        self.identifiers = self.raw.get("identifiers", {})
        self.entity = self.raw.get("entity", {})
        self.golden = self.raw.get("golden", {})
        self.events = self.raw.get("events", [])
        self.rules = self.raw.get("rules", [])
        self.date_order = self.raw.get("dates", {}).get("order", "mdy")
        self.business = self.raw.get("business", {})
        self.anchor = self.entity.get("anchor_source") or next(
            (k for k, v in self.sources.items() if v.get("anchor")), next(iter(self.sources)))

    def source_label(self, source: str) -> str:
        return self.sources.get(source, {}).get("label", source)

    def label_value(self, field_type: str | None, value):
        """Human label for a canonical code, if the field is a coded one."""
        if field_type and field_type.startswith("code:") and value:
            cm = self.code_maps.get(field_type.split(":", 1)[1])
            if cm:
                return cm.label(value)
        return value

    def field_type(self, source: str, field: str):
        return self.sources.get(source, {}).get("fields", {}).get(field, {}).get("type")
