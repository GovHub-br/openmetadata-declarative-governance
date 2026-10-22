"""Gera os YAMLs de resources a partir do estado atual da instancia.

Serve para alinhar o repositorio com a instancia: o primeiro apply depois de
um export deve terminar sem nenhuma alteracao. Ficam de fora a hierarquia dos
`dominios_externos` (mantida pelo sync de outro repositorio), o time raiz
`Organization`, bots e o usuario `admin` embutido da instancia. E-mail de
usuario nunca e exportado: o repositorio e publico.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .client import OpenMetadataClient
from .config import EXTERNAL_DOMAINS_KEY, read_external_domains

IGNORED_USERS = {"admin"}

HEADERS = {
    "domains.yml": """\
# Dominios de negocio/governanca.
# OpenMetadata aceita varios owners usuarios, mas apenas um owner time.
#
# `dominios_externos`: hierarquias mantidas pelo sync de governanca de outro
# repositorio (cada ministerio declara os proprios subdominios e produtos).
# Aqui elas so podem ser referenciadas; declara-las e erro de validacao.
""",
    "personas.yml": """\
# Personas OpenMetadata.
#
# Campos aceitos: nome, nome_exibicao, descricao, padrao, dominios.
# Persona nao tem proprietarios no OpenMetadata.
""",
    "teams.yml": """\
# Times envolvidos nos dominios e produtos de dados.
""",
    "users.yml": """\
# Usuarios OpenMetadata.
#
# Sem e-mail: o repositorio e publico, e usuario existente e identificado pelo
# nome. Para criar um usuario novo, informe o e-mail por variavel de ambiente
# (secret no CI):
#   email: "${USER_FULANO_EMAIL}"
""",
    "data_products.yml": """\
# Produtos de dados.
# Quando inherit_from_domain=true, owners e experts sao herdados do dominio se
# nao forem definidos explicitamente aqui.
""",
}


class Dumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


Dumper.add_representer(str, _str_representer)


def root_of(fqn: str) -> str:
    return fqn.split(".", 1)[0]


def ref_name(ref: Mapping[str, Any]) -> str:
    return str(ref.get("fullyQualifiedName") or ref.get("name"))


def ref_list(refs: Iterable[Mapping[str, Any]] | None, default_type: str) -> list[str]:
    items = []
    for ref in refs or []:
        name = ref_name(ref)
        items.append(name if ref.get("type") == default_type else f"{ref['type']}:{name}")
    return sorted(items)


def ids(refs: Iterable[Mapping[str, Any]] | None) -> set[str]:
    return {str(ref["id"]) for ref in refs or []}


def put_common(entry: dict[str, Any], entity: Mapping[str, Any]) -> None:
    display_name = entity.get("displayName")
    if display_name and display_name != entity["name"]:
        entry["nome_exibicao"] = display_name
    if (entity.get("description") or "").strip():
        entry["descricao"] = entity["description"].strip()


def export_domains(
    client: OpenMetadataClient, external: set[str]
) -> list[dict[str, Any]]:
    domains = [
        d
        for d in client.list_entities("domains", fields=["owners", "experts", "parent"])
        if root_of(d["fullyQualifiedName"]) not in external
    ]
    # pai antes do filho: o subdominio referencia o pai na criacao
    domains.sort(key=lambda d: (d["fullyQualifiedName"].count("."), d["fullyQualifiedName"]))
    exported = []
    for domain in domains:
        entry: dict[str, Any] = {"nome": domain["name"]}
        put_common(entry, domain)
        entry["tipo_dominio"] = domain.get("domainType") or "Aggregate"
        if domain.get("parent"):
            entry["dominio_pai"] = ref_name(domain["parent"])
        if domain.get("owners"):
            entry["proprietarios"] = ref_list(domain["owners"], "team")
        if domain.get("experts"):
            entry["especialistas"] = ref_list(domain["experts"], "user")
        exported.append(entry)
    return exported


def export_personas(client: OpenMetadataClient) -> list[dict[str, Any]]:
    exported = []
    for persona in client.list_entities("personas", fields=["domains"]):
        entry: dict[str, Any] = {"nome": persona["name"]}
        put_common(entry, persona)
        entry["padrao"] = bool(persona.get("default"))
        if persona.get("domains"):
            entry["dominios"] = ref_list(persona["domains"], "domain")
        exported.append(entry)
    return sorted(exported, key=lambda e: e["nome"])


def export_teams(client: OpenMetadataClient) -> list[dict[str, Any]]:
    exported = []
    for team in client.list_entities("teams", fields=["owners", "domains"]):
        if team.get("teamType") == "Organization":
            continue
        entry: dict[str, Any] = {"nome": team["name"]}
        put_common(entry, team)
        if team.get("teamType") and team["teamType"] != "Group":
            entry["tipo_time"] = team["teamType"]
        if team.get("email"):
            entry["email"] = team["email"]
        if team.get("isJoinable") is not None:
            entry["equipe_publica"] = bool(team["isJoinable"])
        if team.get("domains"):
            entry["dominios"] = ref_list(team["domains"], "domain")
        if team.get("owners"):
            entry["proprietarios"] = ref_list(team["owners"], "user")
        exported.append(entry)
    return sorted(exported, key=lambda e: e["nome"])


def export_users(client: OpenMetadataClient) -> list[dict[str, Any]]:
    exported = []
    users = client.list_entities(
        "users",
        fields=["teams", "personas", "roles", "domains"],
        params={"isBot": "false"},
    )
    for user in users:
        if user.get("isBot") or user["name"] in IGNORED_USERS:
            continue
        entry: dict[str, Any] = {"nome": user["name"]}
        put_common(entry, user)
        if user.get("isAdmin"):
            entry["administrador"] = True
        teams = [t for t in user.get("teams") or [] if t.get("name") != "Organization"]
        if teams:
            entry["times"] = ref_list(teams, "team")
        if user.get("personas"):
            entry["personas"] = ref_list(user["personas"], "persona")
        if user.get("roles"):
            entry["papeis"] = ref_list(user["roles"], "role")
        if user.get("domains"):
            entry["dominios"] = ref_list(user["domains"], "domain")
        exported.append(entry)
    return sorted(exported, key=lambda e: e["nome"])


def export_data_products(
    client: OpenMetadataClient, external: set[str]
) -> list[dict[str, Any]]:
    domains = {
        d["fullyQualifiedName"]: d
        for d in client.list_entities("domains", fields=["owners", "experts"])
    }
    exported = []
    products = client.list_entities(
        "dataProducts", fields=["domains", "owners", "experts"]
    )
    for product in products:
        product_domains = [ref_name(d) for d in product.get("domains") or []]
        if not product_domains or any(root_of(d) in external for d in product_domains):
            continue
        entry: dict[str, Any] = {"nome": product["name"]}
        put_common(entry, product)
        entry["dominio"] = product_domains[0] if len(product_domains) == 1 else product_domains
        entry["inherit_from_domain"] = True
        # Explicito so o que diverge do dominio: o que coincide e herdado, e
        # o apply recompoe o mesmo valor.
        domain = domains.get(product_domains[0], {})
        if ids(product.get("owners")) != ids(domain.get("owners")):
            entry["proprietarios"] = ref_list(product.get("owners"), "team")
        if ids(product.get("experts")) != ids(domain.get("experts")):
            entry["especialistas"] = ref_list(product.get("experts"), "user")
        exported.append(entry)
    return sorted(exported, key=lambda e: e["nome"])


def write_resource(path: Path, key: str, items: list[Any], extra: Mapping[str, Any] | None = None) -> None:
    body: dict[str, Any] = dict(extra or {})
    body[key] = items
    text = yaml.dump(body, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=88)
    path.write_text(HEADERS[path.name] + "\n" + text, encoding="utf-8")


def export_resources(client: OpenMetadataClient, directory: str) -> None:
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    domains_file = out / "domains.yml"
    external = sorted(read_external_domains(domains_file)) if domains_file.exists() else []
    external_set = set(external)

    write_resource(
        domains_file,
        "domains",
        export_domains(client, external_set),
        {EXTERNAL_DOMAINS_KEY: external},
    )
    write_resource(out / "personas.yml", "personas", export_personas(client))
    write_resource(out / "teams.yml", "times", export_teams(client))
    write_resource(out / "users.yml", "users", export_users(client))
    write_resource(
        out / "data_products.yml",
        "data_products",
        export_data_products(client, external_set),
    )
