from __future__ import annotations

from typing import Any, Mapping


def reference_ids(value: Any) -> set[str] | None:
    """Ids de uma lista de referencias, ou None se nao for lista de referencias."""
    if not isinstance(value, list):
        return None
    if not all(isinstance(item, Mapping) and "id" in item for item in value):
        return None
    return {str(item["id"]) for item in value}


def same_value(current: Any, desired: Any) -> bool:
    desired_ids = reference_ids(desired)
    if desired_ids is not None:
        # Lista de referencias: a ordem e os campos auxiliares (displayName,
        # inherited, href) variam entre respostas da API; so o id identifica.
        return reference_ids(current or []) == desired_ids
    if isinstance(desired, str) and isinstance(current, str):
        return current.strip() == desired.strip()
    if current is None and desired in ("", [], False):
        return True
    return current == desired


def patch_operations(
    existing: Mapping[str, Any], desired: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """JSON Patch com apenas os campos declarados que diferem da instancia."""
    return [
        {"op": "add", "path": f"/{key}", "value": value}
        for key, value in desired.items()
        if not same_value(existing.get(key), value)
    ]
