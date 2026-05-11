from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


MISSING = object()


@dataclass(frozen=True)
class ReferenceSpec:
    entity_type: str
    name: str
    raw: Mapping[str, Any] | None = None


ENTITY_ENDPOINTS = {
    "user": "users",
    "team": "teams",
    "domain": "domains",
    "persona": "personas",
    "role": "roles",
    "data_product": "dataProducts",
}

DOMAIN_TYPE_ALIASES = {
    "source_aligned": "Source-aligned",
    "source-aligned": "Source-aligned",
    "consumer_aligned": "Consumer-aligned",
    "consumer-aligned": "Consumer-aligned",
    "aggregate": "Aggregate",
}

TEAM_TYPE_ALIASES = {
    "organization": "Organization",
    "business_unit": "BusinessUnit",
    "businessunit": "BusinessUnit",
    "division": "Division",
    "department": "Department",
    "group": "Group",
}


def normalize_key(value: Any) -> str:
    text = str(value)
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore")
    return ascii_text.decode("ascii").strip().lower().replace("-", "_").replace(" ", "_")


def normalized_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {normalize_key(key): item for key, item in value.items()}


def coerce_mapping(value: Any, resource_name: str) -> dict[str, Any]:
    if isinstance(value, str):
        return {"name": value}
    if isinstance(value, Mapping):
        return normalized_mapping(value)
    raise ValueError(f"{resource_name} deve ser string ou objeto YAML")


def get_value(
    item: Mapping[str, Any], aliases: Iterable[str], default: Any = MISSING
) -> Any:
    for alias in aliases:
        normalized = normalize_key(alias)
        if normalized in item:
            return item[normalized]
    if default is not MISSING:
        return default
    alias_list = ", ".join(aliases)
    raise ValueError(f"Campo obrigatorio ausente: {alias_list}")


def has_value(item: Mapping[str, Any], aliases: Iterable[str]) -> bool:
    return any(normalize_key(alias) in item for alias in aliases)


def optional_str(
    item: Mapping[str, Any], aliases: Iterable[str], default: str | None = None
) -> str | None:
    value = get_value(item, aliases, default)
    if value is None:
        return default
    return str(value)


def as_list(value: Any) -> list[Any]:
    if value is MISSING or value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def as_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is MISSING or value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = normalize_key(value)
        if normalized in {"true", "t", "yes", "y", "sim", "s", "1"}:
            return True
        if normalized in {"false", "f", "no", "n", "nao", "0"}:
            return False
    return bool(value)


def reference_names(values: Any) -> list[str]:
    names: list[str] = []
    for value in as_list(values):
        if isinstance(value, Mapping):
            name = value.get("fullyQualifiedName") or value.get("name")
            if name:
                names.append(str(name))
        elif value:
            names.append(str(value))
    return names


def first_or_warn(
    values: list[Any],
    resource_name: str,
    field_name: str,
    warnings: list[str],
) -> Any | None:
    if not values:
        return None
    if len(values) > 1:
        warnings.append(
            f"{resource_name}: OpenMetadata aceita um unico {field_name}; "
            f"usando {values[0]!r} e ignorando {values[1:]!r}."
        )
    return values[0]


def normalize_domain_type(value: Any) -> str:
    if value is MISSING or value is None:
        return "Aggregate"
    key = normalize_key(value)
    return DOMAIN_TYPE_ALIASES.get(key, str(value))


def normalize_team_type(value: Any) -> str:
    if value is MISSING or value is None:
        return "Group"
    key = normalize_key(value)
    return TEAM_TYPE_ALIASES.get(key, str(value))


def parse_reference(value: Any, default_type: str) -> ReferenceSpec:
    if isinstance(value, str):
        if ":" in value:
            prefix, name = value.split(":", 1)
            return ReferenceSpec(normalize_key(prefix), name.strip())
        return ReferenceSpec(default_type, value.strip())

    if isinstance(value, Mapping):
        normalized = normalized_mapping(value)
        entity_type = str(get_value(normalized, ["type", "tipo"], default_type))
        name = str(get_value(normalized, ["name", "nome", "fqn"]))
        return ReferenceSpec(normalize_key(entity_type), name, value)

    raise ValueError(f"Referencia invalida: {value!r}")


def reference_entity_name(entity: Mapping[str, Any]) -> str:
    return str(entity.get("fullyQualifiedName") or entity.get("name"))


def get_resource_items(
    config: Mapping[str, Any], aliases: Iterable[str], resource_name: str
) -> list[dict[str, Any]]:
    for alias in aliases:
        normalized = normalize_key(alias)
        if normalized in config:
            return [
                coerce_mapping(item, resource_name)
                for item in as_list(config[normalized])
            ]
    return []

