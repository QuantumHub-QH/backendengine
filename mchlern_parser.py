"""Adapter from Ghosteined/rbxm_parser objects to MCHLERN's JSON manifest.

The upstream parser is read-only and supports binary .rbxm/.rbxl files.
It does not support XML .rbxmx/.rbxlx files.
"""
from typing import Any


def _get_name(instance: Any) -> str:
    try:
        value = instance.get_property("Name", "Unnamed")
    except Exception:
        value = "Unnamed"
    return str(value or "Unnamed")


def _get_source(instance: Any):
    try:
        value = instance.get_property("Source")
    except Exception:
        value = None
    return value if isinstance(value, str) else None


def _get_children(instance: Any):
    children = getattr(instance, "children", [])
    return children if isinstance(children, (list, tuple)) else []


def parse_bytes(data: bytes, file_type: str) -> dict:
    if file_type not in ("rbxm", "rbxl"):
        raise ValueError("Only binary RBXM/RBXL files are supported.")

    try:
        from rbxm_parser import parse_rbxm_bytes
    except ImportError as exc:
        raise RuntimeError(
            "Dependency rbxm_parser belum terpasang. Periksa requirements.txt Railway."
        ) from exc

    try:
        parsed = parse_rbxm_bytes(data)
    except Exception as exc:
        raise ValueError(f"Roblox binary parser rejected the file: {exc}") from exc

    roots = getattr(parsed, "tree", None)
    if not isinstance(roots, (list, tuple)):
        raise ValueError("Parser returned an invalid instance tree.")

    def convert(instance):
        class_name = str(getattr(instance, "class_name", "Unknown") or "Unknown")
        name = _get_name(instance)
        source = _get_source(instance)
        node = {
            "className": class_name,
            "name": name,
            "children": [convert(child) for child in _get_children(instance)],
        }
        if source is not None:
            node["scriptSource"] = source
        return node

    metadata = getattr(parsed, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "tree": [convert(root) for root in roots],
        "metadata": {str(k): str(v) for k, v in metadata.items()},
    }
