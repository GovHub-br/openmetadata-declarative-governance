from __future__ import annotations

from typing import Any, Mapping

from .client import OpenMetadataClient
from .errors import OpenMetadataError
from .utils import (
    as_bool,
    as_list,
    first_or_warn,
    get_resource_items,
    get_value,
    has_value,
    normalize_domain_type,
    normalize_team_type,
    optional_str,
    reference_entity_name,
    reference_names,
)
from .validation import validate_config_rules


def base_domain_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": str(get_value(item, ["name", "nome"])),
        "domainType": normalize_domain_type(
            get_value(item, ["domainType", "tipo_dominio"], None)
        ),
    }
    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description
    parent = optional_str(item, ["parent", "parentDomain", "dominio_pai"])
    if parent:
        payload["parent"] = parent
    return payload


def domain_create_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    *,
    include_refs: bool,
) -> dict[str, Any]:
    payload = base_domain_payload(item)
    if include_refs and has_value(item, ["owners", "proprietarios"]):
        payload["owners"] = client.resolve_references(
            get_value(item, ["owners", "proprietarios"]), "team"
        )
    if include_refs and has_value(item, ["experts", "especialistas"]):
        payload["experts"] = client.resolve_reference_names(
            get_value(item, ["experts", "especialistas"]), "user"
        )
    return payload


def domain_patch_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    *,
    include_refs: bool,
) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in base_domain_payload(item).items()
        if key not in {"name"}
    }
    if include_refs and has_value(item, ["owners", "proprietarios"]):
        payload["owners"] = client.resolve_references(
            get_value(item, ["owners", "proprietarios"]), "team"
        )
    if include_refs and has_value(item, ["experts", "especialistas"]):
        payload["experts"] = client.resolve_references(
            get_value(item, ["experts", "especialistas"]), "user"
        )
    return payload


def team_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    warnings: list[str],
    *,
    include_owners: bool,
) -> dict[str, Any]:
    name = str(get_value(item, ["name", "nome"]))
    payload: dict[str, Any] = {
        "name": name,
        "teamType": normalize_team_type(get_value(item, ["teamType", "tipo_time"], None)),
    }
    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    email = optional_str(item, ["email"])
    is_joinable = as_bool(
        get_value(item, ["isJoinable", "is_joinable", "equipe_publica"], None)
    )
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description
    if email:
        payload["email"] = email
    if is_joinable is not None:
        payload["isJoinable"] = is_joinable

    domains = as_list(get_value(item, ["domain", "dominio", "domains", "dominios"], None))
    if domains:
        payload["domains"] = [
            reference_entity_name(client.resolve_reference(domain, "domain"))
            for domain in domains
        ]

    if include_owners and has_value(item, ["owners", "proprietarios"]):
        payload["owners"] = client.resolve_references(
            get_value(item, ["owners", "proprietarios"]), "user"
        )

    return payload


def user_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    warnings: list[str],
    *,
    for_patch: bool,
) -> dict[str, Any]:
    email = optional_str(item, ["email"])
    name = optional_str(item, ["name", "nome"])
    if not name and email:
        name = email.split("@", 1)[0]
    if not name:
        raise ValueError("Usuario precisa de name/nome ou email.")
    if not email:
        raise ValueError(f"Usuario {name} precisa de email.")

    payload: dict[str, Any] = {"name": name, "email": email}
    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description

    teams = as_list(get_value(item, ["teams", "times"], None))
    if teams:
        if for_patch:
            payload["teams"] = client.resolve_references(teams, "team")
        else:
            payload["teams"] = [
                client.resolve_reference(team, "team")["id"] for team in teams
            ]

    roles = as_list(get_value(item, ["roles", "papeis"], None))
    if roles:
        if for_patch:
            payload["roles"] = client.resolve_references(roles, "role")
        else:
            payload["roles"] = [
                client.resolve_reference(role, "role")["id"] for role in roles
            ]

    personas = as_list(get_value(item, ["personas"], None))
    if personas:
        payload["personas"] = client.resolve_references(personas, "persona")

    domain = first_or_warn(
        as_list(get_value(item, ["domain", "dominio", "domains", "dominios"], None)),
        f"usuario {name}",
        "dominio",
        warnings,
    )
    if domain:
        if for_patch:
            payload["domains"] = client.resolve_references([domain], "domain")
        else:
            payload["domains"] = client.resolve_reference_names([domain], "domain")

    is_bot = as_bool(get_value(item, ["isBot", "is_bot"], None))
    is_admin = as_bool(get_value(item, ["isAdmin", "is_admin"], None))
    if is_bot is not None:
        payload["isBot"] = is_bot
    if is_admin is not None:
        payload["isAdmin"] = is_admin

    return payload


def data_product_create_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
) -> dict[str, Any]:
    name = str(get_value(item, ["name", "nome"]))
    domains = as_list(get_value(item, ["domain", "dominio", "domains", "dominios"]))
    if not domains:
        raise ValueError(f"data_product {name} precisa de dominio/domains.")
    payload: dict[str, Any] = {
        "name": name,
        "domains": client.resolve_reference_names(domains, "domain"),
    }

    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description

    domain_entity = inherited_domain(item, client, domains)
    if has_value(item, ["owners", "proprietarios"]):
        payload["owners"] = client.resolve_references(
            get_value(item, ["owners", "proprietarios"]), "team"
        )
    elif domain_entity and domain_entity.get("owners"):
        payload["owners"] = domain_entity["owners"]

    if has_value(item, ["experts", "especialistas"]):
        payload["experts"] = client.resolve_reference_names(
            get_value(item, ["experts", "especialistas"]), "user"
        )
    elif domain_entity and domain_entity.get("experts"):
        payload["experts"] = reference_names(domain_entity["experts"])

    return payload


def data_product_patch_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
) -> dict[str, Any]:
    name = str(get_value(item, ["name", "nome"]))
    domains = as_list(get_value(item, ["domain", "dominio", "domains", "dominios"]))
    if not domains:
        raise ValueError(f"data_product {name} precisa de dominio/domains.")

    payload: dict[str, Any] = {
        "domains": client.resolve_references(domains, "domain"),
    }
    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description

    domain_entity = inherited_domain(item, client, domains)
    if has_value(item, ["owners", "proprietarios"]):
        payload["owners"] = client.resolve_references(
            get_value(item, ["owners", "proprietarios"]), "team"
        )
    elif domain_entity and domain_entity.get("owners"):
        payload["owners"] = domain_entity["owners"]

    if has_value(item, ["experts", "especialistas"]):
        payload["experts"] = client.resolve_references(
            get_value(item, ["experts", "especialistas"]), "user"
        )
    elif domain_entity and domain_entity.get("experts"):
        payload["experts"] = domain_entity["experts"]

    return payload


def inherited_domain(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    domains: list[Any],
) -> dict[str, Any] | None:
    inherit_from_domain = as_bool(
        get_value(item, ["inherit_from_domain", "herdar_do_dominio"], True),
        True,
    )
    if not inherit_from_domain:
        return None
    if has_value(item, ["owners", "proprietarios"]) and has_value(
        item, ["experts", "especialistas"]
    ):
        return None
    domain_entity = client.get_by_name(
        "domain", str(domains[0]), fields=["owners", "experts"]
    )
    if not domain_entity:
        raise OpenMetadataError(f"Dominio nao encontrado: {domains[0]}")
    return domain_entity


def create_or_patch_domain(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    *,
    include_refs: bool,
) -> None:
    name = str(get_value(item, ["name", "nome"]))
    existing = client.get_by_name("domain", name, fields=["owners", "experts"])
    if existing:
        payload = domain_patch_payload(item, client, include_refs=include_refs)
        print(f"[domain] atualizando {name}")
        client.patch_entity("domains", existing["id"], payload, "domain")
        return

    payload = domain_create_payload(item, client, include_refs=include_refs)
    print(f"[domain] criando {name}")
    client.put_entity("domains", payload, "domain")


def create_or_patch_team(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    warnings: list[str],
    *,
    include_owners: bool,
) -> None:
    payload = team_payload(item, client, warnings, include_owners=include_owners)
    name = str(payload["name"])
    existing = client.get_by_name("team", name, fields=["owners", "domains"])
    if existing:
        mutable_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"name", "teamType"}
        }
        if "domains" in mutable_payload:
            mutable_payload["domains"] = client.resolve_references(
                mutable_payload["domains"], "domain"
            )
        if mutable_payload:
            print(f"[team] atualizando {name}")
            client.patch_entity("teams", existing["id"], mutable_payload, "team")
        else:
            print(f"[team] sem mudancas para {name}")
        return

    print(f"[team] criando {name}")
    client.post_entity("teams", payload, "team")


def create_or_patch_user(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    warnings: list[str],
) -> None:
    name = optional_str(item, ["name", "nome"])
    email = optional_str(item, ["email"])
    if not name and email:
        name = email.split("@", 1)[0]
    if not name:
        raise ValueError("Usuario precisa de name/nome ou email.")
    password = optional_str(item, ["password", "senha"])
    confirm_password = optional_str(
        item, ["confirmPassword", "confirm_password", "confirmar_senha"], password
    )

    existing = client.get_by_name(
        "user", name, fields=["teams", "personas", "domains", "roles"]
    )
    if existing:
        payload = user_payload(item, client, warnings, for_patch=True)
        mutable_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"name", "password", "confirmPassword"}
        }
        print(f"[user] atualizando {name}")
        client.patch_entity("users", existing["id"], mutable_payload, "user")
        if password:
            print(f"[user] atualizando senha de {name}")
            client.change_user_password(name, password, str(confirm_password))
        return

    payload = user_payload(item, client, warnings, for_patch=False)
    print(f"[user] criando {name}")
    client.put_entity("users", payload, "user")
    if password:
        print(f"[user] definindo senha de {name}")
        client.change_user_password(name, password, str(confirm_password))


def create_or_patch_data_product(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
) -> None:
    name = str(get_value(item, ["name", "nome"]))
    existing = client.get_by_name(
        "data_product", name, fields=["owners", "experts", "domains"]
    )
    if existing:
        payload = data_product_patch_payload(item, client)
        print(f"[dataProduct] atualizando {name}")
        client.patch_entity("dataProducts", existing["id"], payload, "data_product")
        return

    payload = data_product_create_payload(item, client)
    print(f"[dataProduct] criando {name}")
    client.put_entity("dataProducts", payload, "data_product")


def apply_config(config: dict[str, Any], client: OpenMetadataClient) -> list[str]:
    validate_config_rules(config)
    warnings: list[str] = []
    domains = get_resource_items(config, ["domains", "dominios"], "domain")
    teams = get_resource_items(config, ["teams", "times", "time"], "team")
    users = get_resource_items(config, ["users", "usuarios"], "user")
    data_products = get_resource_items(
        config,
        ["data_products", "dataProducts", "produtos_dados", "produtos_de_dados"],
        "data_product",
    )

    for domain in domains:
        create_or_patch_domain(domain, client, include_refs=False)

    for team in teams:
        create_or_patch_team(team, client, warnings, include_owners=False)

    for user in users:
        create_or_patch_user(user, client, warnings)

    for domain in domains:
        if has_value(domain, ["owners", "proprietarios"]) or has_value(
            domain, ["experts", "especialistas"]
        ):
            create_or_patch_domain(domain, client, include_refs=True)

    for team in teams:
        create_or_patch_team(team, client, warnings, include_owners=True)

    for data_product in data_products:
        create_or_patch_data_product(data_product, client)

    return warnings

