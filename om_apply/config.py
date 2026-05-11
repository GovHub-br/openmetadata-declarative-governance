from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from .utils import normalized_mapping, normalize_key


ENV_VAR_PATTERN = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}"
)

RESOURCE_FILES = {
    "domains": ("domains.yml", "domains.yaml", "dominios.yml", "dominios.yaml"),
    "teams": ("teams.yml", "teams.yaml", "times.yml", "times.yaml"),
    "users": ("users.yml", "users.yaml", "usuarios.yml", "usuarios.yaml"),
    "personas": ("personas.yml", "personas.yaml"),
    "data_products": (
        "data_products.yml",
        "data_products.yaml",
        "produtos_dados.yml",
        "produtos_dados.yaml",
        "produtos_de_dados.yml",
        "produtos_de_dados.yaml",
    ),
}

RESOURCE_KEYS = {
    "domains": ("domains", "dominios"),
    "teams": ("teams", "times", "time"),
    "users": ("users", "usuarios"),
    "personas": ("personas",),
    "data_products": (
        "data_products",
        "dataproducts",
        "produtos_dados",
        "produtos_de_dados",
    ),
}


def expand_env_string(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        default = match.group(2)
        return os.getenv(name, default if default is not None else "")

    return ENV_VAR_PATTERN.sub(replace, value)


def expand_env_values(value: Any) -> Any:
    if isinstance(value, str):
        return expand_env_string(value)
    if isinstance(value, list):
        return [expand_env_values(item) for item in value]
    if isinstance(value, Mapping):
        return {key: expand_env_values(item) for key, item in value.items()}
    return value


def read_yaml_file(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def read_config(path: str) -> dict[str, Any]:
    config_path = Path(path)
    if config_path.is_dir():
        return read_config_directory(config_path)
    return read_config_file(config_path)


def read_config_file(path: Path) -> dict[str, Any]:
    data = read_yaml_file(path)
    if not isinstance(data, Mapping):
        raise ValueError("O arquivo YAML deve conter um objeto no topo.")
    return normalized_mapping(expand_env_values(data))


def read_config_directory(path: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for resource_key, filenames in RESOURCE_FILES.items():
        resource_file = next(
            (path / filename for filename in filenames if (path / filename).exists()),
            None,
        )
        if resource_file is None:
            merged[resource_key] = []
            continue
        merged[resource_key] = read_resource_file(resource_file, resource_key)
    return normalized_mapping(expand_env_values(merged))


def read_resource_file(path: Path, resource_key: str) -> list[Any]:
    data = read_yaml_file(path)
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        normalized = normalized_mapping(data)
        for key in RESOURCE_KEYS[resource_key]:
            normalized_key = normalize_key(key)
            if normalized_key in normalized:
                return normalized[normalized_key] or []
    raise ValueError(
        f"{path}: use uma lista YAML ou um objeto com a chave {resource_key!r}."
    )
