"""OpenMetadata em memoria, so com o que o reconciler usa da API."""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any
from urllib.parse import unquote, urlparse

API = "https://om.test/api/v1"

TYPES = {
    "domains": "domain",
    "teams": "team",
    "users": "user",
    "personas": "persona",
    "roles": "role",
    "policies": "policy",
    "dataProducts": "dataProduct",
}


class Response:
    def __init__(self, status_code: int, body: Any = None) -> None:
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body) if body is not None else ""
        self.content = self.text.encode()

    def json(self) -> Any:
        return self._body


class FakeOpenMetadata:
    def __init__(self) -> None:
        self.store: dict[str, list[dict[str, Any]]] = {ep: [] for ep in TYPES}
        self.mutations: list[tuple[str, str, Any]] = []
        self.headers: dict[str, str] = {}

    # ── montagem do estado ────────────────────────────────────────────────
    def add(self, endpoint: str, **fields: Any) -> dict[str, Any]:
        entity = {"id": str(uuid.uuid4()), **fields}
        parent = entity.get("parent")
        entity["fullyQualifiedName"] = (
            f"{parent['fullyQualifiedName']}.{entity['name']}" if parent else entity["name"]
        )
        self.store[endpoint].append(entity)
        return entity

    def ref(self, endpoint: str, name: str) -> dict[str, Any]:
        entity = self.find(endpoint, name)
        assert entity, f"{endpoint}:{name} nao existe no fake"
        return {
            "id": entity["id"],
            "type": TYPES[endpoint],
            "name": entity["name"],
            "fullyQualifiedName": entity["fullyQualifiedName"],
        }

    def find(self, endpoint: str, fqn: str) -> dict[str, Any] | None:
        return next(
            (e for e in self.store[endpoint] if e["fullyQualifiedName"] == fqn), None
        )

    def by_id(self, endpoint: str, entity_id: str) -> dict[str, Any] | None:
        return next((e for e in self.store[endpoint] if e["id"] == entity_id), None)

    # ── interface de requests.Session ─────────────────────────────────────
    def _route(self, url: str) -> list[str]:
        return [unquote(part) for part in urlparse(url).path.split("/api/v1/", 1)[1].split("/")]

    def get(self, url: str, params: dict | None = None, timeout: float = 0) -> Response:
        parts = self._route(url)
        endpoint = parts[0]
        if len(parts) == 3 and parts[1] == "name":
            entity = self.find(endpoint, parts[2])
            return Response(200, copy.deepcopy(entity)) if entity else Response(404, {})
        data = self.store[endpoint]
        if endpoint == "users" and (params or {}).get("isBot") == "false":
            data = [u for u in data if not u.get("isBot")]
        return Response(200, {"data": copy.deepcopy(data), "paging": {}})

    def request(self, method: str, url: str, json: Any = None, timeout: float = 0) -> Response:
        endpoint = self._route(url)[0]
        self.mutations.append((method, endpoint, json))
        name = json["name"]
        entity = self.find(endpoint, name) or {"id": str(uuid.uuid4())}
        entity.update(self._as_entity(json))
        parent = entity.get("parent")
        entity["fullyQualifiedName"] = (
            f"{parent['fullyQualifiedName']}.{name}" if parent else name
        )
        if entity not in self.store[endpoint]:
            self.store[endpoint].append(entity)
        return Response(201, copy.deepcopy(entity))

    def patch(self, url: str, json: Any = None, headers: Any = None, timeout: float = 0) -> Response:
        endpoint, entity_id = self._route(url)[:2]
        self.mutations.append(("PATCH", endpoint, json))
        entity = self.by_id(endpoint, entity_id)
        if not entity:
            return Response(404, {})
        for op in json:
            entity[op["path"].lstrip("/")] = op["value"]
        return Response(200, copy.deepcopy(entity))

    def _as_entity(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Payload de criacao usa nomes/ids; a entidade guarda referencias."""
        entity = dict(payload)
        for field, endpoint in (("domains", "domains"), ("experts", "users")):
            if field in entity:
                entity[field] = [self.ref(endpoint, name) for name in entity[field]]
        if "policies" in entity:
            entity["policies"] = [self.ref("policies", name) for name in entity["policies"]]
        for field, endpoint in (("teams", "teams"), ("roles", "roles"), ("defaultRoles", "roles")):
            if field in entity and entity[field] and isinstance(entity[field][0], str):
                entity[field] = [
                    self.ref(endpoint, self.by_id(endpoint, i)["fullyQualifiedName"])
                    for i in entity[field]
                ]
        if isinstance(entity.get("parent"), str):
            entity["parent"] = self.ref("domains", entity["parent"])
        return entity
