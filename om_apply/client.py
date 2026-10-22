from __future__ import annotations

import json
from typing import Any, Iterable, Mapping
from urllib.parse import quote

import requests

from .audit import AuditLogger, redact
from .diff import patch_operations
from .errors import OpenMetadataError
from .utils import (
    ENTITY_ENDPOINTS,
    as_list,
    normalize_key,
    parse_reference,
)


class OpenMetadataClient:
    def __init__(
        self,
        host: str,
        token: str,
        timeout: float,
        dry_run: bool = False,
        audit: AuditLogger | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.api_url = (
            self.host if self.host.endswith("/api/v1") else f"{self.host}/api/v1"
        )
        self.timeout = timeout
        self.dry_run = dry_run
        self.audit = audit or AuditLogger()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )
        self.cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.counts = {"criados": 0, "atualizados": 0, "sem_mudanca": 0}

    def remember(self, entity_type: str, entity: Mapping[str, Any]) -> None:
        for key in ("fullyQualifiedName", "name", "displayName"):
            name = entity.get(key)
            if name:
                self.cache[(entity_type, str(name))] = dict(entity)

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> dict[str, Any]:
        method = method.upper()
        if self.dry_run and method in {"POST", "PUT", "PATCH"}:
            print(f"DRY-RUN {method} {path}")
            if payload is not None:
                print(json.dumps(redact(payload), ensure_ascii=False, indent=2, sort_keys=True))
            name = str(payload.get("name", "dry-run")) if payload else "dry-run"
            return {
                "id": f"dry-run-{normalize_key(name)}",
                "name": name,
                "fullyQualifiedName": name,
                **(dict(payload or {})),
            }

        response = self.session.request(
            method,
            f"{self.api_url}{path}",
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code not in expected:
            self.audit.api_error(
                method=method,
                path=path,
                status_code=response.status_code,
                response_body=response.text,
                payload=payload,
            )
            raise OpenMetadataError(
                f"{method} {path} retornou {response.status_code}: "
                f"{response.text[:1200]}"
            )
        if not response.content:
            return {}
        return response.json()

    def get_by_name(
        self,
        entity_type: str,
        fqn: str,
        fields: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        # Com `fields`, quem chama vai comparar esses campos com o YAML: uma
        # entidade em cache, buscada antes sem eles, faria o diff enxergar
        # times/dominios vazios e reescreve-los.
        cached = self.cache.get((entity_type, fqn))
        if cached and not fields:
            return cached

        endpoint = ENTITY_ENDPOINTS.get(entity_type)
        if not endpoint:
            raise ValueError(f"Tipo de referencia nao suportado: {entity_type}")

        query = ""
        if fields:
            query = f"?fields={','.join(fields)}"

        response = self.session.get(
            f"{self.api_url}/{endpoint}/name/{quote(fqn, safe='')}{query}",
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return self.find_by_display_name(entity_type, fqn)
        if response.status_code != 200:
            self.audit.api_error(
                method="GET",
                path=f"/{endpoint}/name/{fqn}",
                status_code=response.status_code,
                response_body=response.text,
            )
            raise OpenMetadataError(
                f"GET /{endpoint}/name/{fqn} retornou "
                f"{response.status_code}: {response.text[:1200]}"
            )
        entity = response.json()
        self.remember(entity_type, entity)
        return entity

    def find_by_display_name(
        self,
        entity_type: str,
        name_or_display_name: str,
    ) -> dict[str, Any] | None:
        endpoint = ENTITY_ENDPOINTS.get(entity_type)
        if not endpoint:
            raise ValueError(f"Tipo de referencia nao suportado: {entity_type}")

        expected = str(name_or_display_name)
        for entity in self.list_entities(endpoint):
            candidates = {
                str(entity.get("name", "")),
                str(entity.get("fullyQualifiedName", "")),
                str(entity.get("displayName", "")),
            }
            if expected in candidates:
                self.remember(entity_type, entity)
                return entity
        return None

    def list_entities(
        self,
        endpoint: str,
        fields: Iterable[str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Todas as entidades do endpoint, seguindo a paginacao por cursor."""
        query: dict[str, str] = {"limit": "100", **(params or {})}
        if fields:
            query["fields"] = ",".join(fields)
        entities: list[dict[str, Any]] = []
        while True:
            response = self.session.get(
                f"{self.api_url}/{endpoint}", params=query, timeout=self.timeout
            )
            if response.status_code != 200:
                self.audit.api_error(
                    method="GET",
                    path=f"/{endpoint}",
                    status_code=response.status_code,
                    response_body=response.text,
                )
                raise OpenMetadataError(
                    f"GET /{endpoint} retornou {response.status_code}: "
                    f"{response.text[:1200]}"
                )
            body = response.json()
            entities.extend(body.get("data", []))
            after = (body.get("paging") or {}).get("after")
            if not after:
                return entities
            query["after"] = after

    def resolve_reference(self, value: Any, default_type: str) -> dict[str, Any]:
        spec = parse_reference(value, default_type)
        # Sem placeholder no dry-run: o que o apply nao acharia, o dry-run
        # tambem nao acha. Entidades criadas no proprio dry-run ja estao no
        # cache, entao referencias a elas resolvem.
        entity = self.get_by_name(spec.entity_type, spec.name)
        if not entity:
            raise OpenMetadataError(
                f"Referencia nao encontrada: {spec.entity_type}:{spec.name}"
            )

        ref = {
            "id": entity["id"],
            "type": spec.entity_type,
            "name": entity.get("name", spec.name),
        }
        if entity.get("fullyQualifiedName"):
            ref["fullyQualifiedName"] = entity["fullyQualifiedName"]
        return ref

    def resolve_references(
        self, values: Any, default_type: str
    ) -> list[dict[str, Any]]:
        return [self.resolve_reference(value, default_type) for value in as_list(values)]

    def resolve_reference_names(self, values: Any, default_type: str) -> list[str]:
        names: list[str] = []
        for value in as_list(values):
            ref = self.resolve_reference(value, default_type)
            names.append(str(ref.get("fullyQualifiedName") or ref["name"]))
        return names

    def put_entity(
        self, endpoint: str, payload: Mapping[str, Any], entity_type: str
    ) -> dict[str, Any]:
        entity = self.request("PUT", f"/{endpoint}", payload=payload)
        self.remember(entity_type, entity)
        self.counts["criados"] += 1
        return entity

    def post_entity(
        self, endpoint: str, payload: Mapping[str, Any], entity_type: str
    ) -> dict[str, Any]:
        entity = self.request("POST", f"/{endpoint}", payload=payload)
        self.remember(entity_type, entity)
        self.counts["criados"] += 1
        return entity

    def patch_entity(
        self,
        endpoint: str,
        existing: Mapping[str, Any],
        desired: Mapping[str, Any],
        entity_type: str,
    ) -> dict[str, Any]:
        """Envia so os campos que diferem; sem diferenca, nao chama a API."""
        label = f"[{entity_type}] {existing.get('name')}"
        json_patch = patch_operations(existing, desired)
        if not json_patch:
            print(f"{label}: sem mudancas")
            self.counts["sem_mudanca"] += 1
            return dict(existing)

        changed = ", ".join(op["path"].lstrip("/") for op in json_patch)
        print(f"{label}: atualizando {changed}")
        self.counts["atualizados"] += 1
        path = f"/{endpoint}/{quote(str(existing['id']), safe='')}"
        if self.dry_run:
            print(f"DRY-RUN PATCH {path}")
            print(json.dumps(json_patch, ensure_ascii=False, indent=2, sort_keys=True))
            entity = {**existing, **desired}
            self.remember(entity_type, entity)
            return entity

        response = self.session.patch(
            f"{self.api_url}{path}",
            json=json_patch,
            headers={"Content-Type": "application/json-patch+json"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            self.audit.api_error(
                method="PATCH",
                path=path,
                status_code=response.status_code,
                response_body=response.text,
                payload=json_patch,
            )
            raise OpenMetadataError(
                f"PATCH {path} retornou {response.status_code}: "
                f"{response.text[:1200]}"
            )
        entity = response.json()
        self.remember(entity_type, entity)
        return entity
