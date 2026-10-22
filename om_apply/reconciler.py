from __future__ import annotations

from typing import Any, Mapping

from .client import OpenMetadataClient
from .errors import OpenMetadataError
from .utils import (
    as_bool,
    as_list,
    get_resource_items,
    get_value,
    has_value,
    normalized_mapping,
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
    # `parent` so vale na criacao: mover subdominio de pai nao e um PATCH.
    payload = {
        key: value
        for key, value in base_domain_payload(item).items()
        if key not in {"name", "parent"}
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


RULE_FIELDS = ("name", "description", "effect", "resources", "operations", "condition")


def normalize_rules(rules: Any) -> list[dict[str, Any]]:
    """Regras na forma que o OpenMetadata devolve: listas ordenadas, sem vazios.

    O servidor ordena recursos e operacoes ao gravar; sem normalizar, o diff
    acusaria mudanca a cada execucao.
    """
    normalized = []
    for rule in as_list(rules):
        normalized.append(
            {
                key: sorted(value) if isinstance(value, list) else value
                for key, value in rule.items()
                if key in RULE_FIELDS and value not in (None, "", [])
            }
        )
    return normalized


def rule_from_item(rule: Mapping[str, Any]) -> dict[str, Any]:
    rule = normalized_mapping(rule)
    return {
        "name": str(get_value(rule, ["name", "nome"])),
        "description": optional_str(rule, ["description", "descricao"]),
        "effect": str(get_value(rule, ["effect", "efeito"])).lower(),
        "resources": [str(r) for r in as_list(get_value(rule, ["resources", "recursos"]))],
        "operations": [str(o) for o in as_list(get_value(rule, ["operations", "operacoes"]))],
        "condition": optional_str(rule, ["condition", "condicao"]),
    }


def policy_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": str(get_value(item, ["name", "nome"])),
        "rules": normalize_rules(
            [rule_from_item(rule) for rule in as_list(get_value(item, ["rules", "regras"]))]
        ),
    }
    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description
    return payload


def create_or_patch_policy(item: Mapping[str, Any], client: OpenMetadataClient) -> None:
    payload = policy_payload(item)
    name = payload["name"]
    existing = client.get_by_name("policy", name, fields=["rules"])
    if existing:
        current = {**existing, "rules": normalize_rules(existing.get("rules"))}
        mutable = {key: value for key, value in payload.items() if key != "name"}
        client.patch_entity("policies", current, mutable, "policy")
        return
    print(f"[policy] criando {name}")
    client.put_entity("policies", payload, "policy")


def create_or_patch_role(item: Mapping[str, Any], client: OpenMetadataClient) -> None:
    name = str(get_value(item, ["name", "nome"]))
    policies = as_list(get_value(item, ["policies", "politicas"]))
    payload: dict[str, Any] = {"name": name}
    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description

    existing = client.get_by_name("role", name, fields=["policies"])
    if existing:
        mutable = {key: value for key, value in payload.items() if key != "name"}
        mutable["policies"] = client.resolve_references(policies, "policy")
        client.patch_entity("roles", existing, mutable, "role")
        return
    payload["policies"] = client.resolve_reference_names(policies, "policy")
    print(f"[role] criando {name}")
    client.put_entity("roles", payload, "role")


def missing_destination_config(item: Mapping[str, Any]) -> list[str]:
    """O que falta para montar o destino: endpoint e segredo vem do ambiente."""
    destino = normalized_mapping(get_value(item, ["destination", "destino"]))
    missing = []
    if not optional_str(destino, ["endpoint"]):
        missing.append("endpoint")
    if not optional_str(destino, ["secretKey", "secret_key", "segredo"]):
        missing.append("segredo")
    return missing


def webhook_destination(item: Mapping[str, Any]) -> dict[str, Any]:
    destino = normalized_mapping(get_value(item, ["destination", "destino"]))
    secret = optional_str(destino, ["secretKey", "secret_key", "segredo"])
    return {
        "category": "External",
        "type": "Webhook",
        "timeout": int(get_value(destino, ["timeout"], 10)),
        "config": {
            "endpoint": str(get_value(destino, ["endpoint"])),
            "httpMethod": "POST",
            "authType": {"type": "bearer", "secretKey": secret},
        },
    }


def destination_endpoint(subscription: Mapping[str, Any]) -> str | None:
    for destination in subscription.get("destinations") or []:
        endpoint = (destination.get("config") or {}).get("endpoint")
        if endpoint:
            return str(endpoint)
    return None


def create_or_patch_event_subscription(
    item: Mapping[str, Any], client: OpenMetadataClient, warnings: list[str]
) -> None:
    """Alerta com destino webhook.

    O OpenMetadata nao devolve o segredo do webhook na leitura, entao o diff
    compara o endpoint; o destino (com o segredo) so e reenviado quando ele
    muda.

    Endpoint e segredo vem do ambiente. Enquanto faltarem (o receptor ainda nao
    esta implantado, por exemplo), o alerta nao e criado nem tem o destino
    trocado: vira aviso, e o resto do apply segue.
    """
    name = str(get_value(item, ["name", "nome"]))
    payload: dict[str, Any] = {"name": name}
    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description
    enabled = as_bool(get_value(item, ["enabled", "ativo"], True), True)
    endpoint = str(
        get_value(normalized_mapping(get_value(item, ["destination", "destino"])), ["endpoint"])
    )

    missing = missing_destination_config(item)
    pending = (
        f"alerta {name}: destino sem {' e '.join(missing)} no ambiente "
        "(ver event_subscriptions.yml); "
    )

    existing = client.get_by_name("event_subscription", name, fields=["destinations"])
    if existing:
        mutable = {key: value for key, value in payload.items() if key != "name"}
        mutable["enabled"] = enabled
        if destination_endpoint(existing) != endpoint:
            if missing:
                warnings.append(pending + "o destino atual foi mantido.")
            else:
                mutable["destinations"] = [webhook_destination(item)]
        client.patch_entity("events/subscriptions", existing, mutable, "event_subscription")
        return

    if missing:
        warnings.append(pending + "o alerta sera criado quando elas existirem.")
        return

    payload.update(
        {
            "alertType": str(get_value(item, ["alertType", "tipo_alerta"], "Notification")),
            "resources": [str(r) for r in as_list(get_value(item, ["resources", "recursos"]))],
            "enabled": enabled,
            "retries": int(get_value(item, ["retries", "tentativas"], 3)),
            "destinations": [webhook_destination(item)],
        }
    )
    print(f"[event_subscription] criando {name}")
    client.post_entity("events/subscriptions", payload, "event_subscription")


def base_persona_payload(item: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": str(get_value(item, ["name", "nome"]))}
    display_name = optional_str(item, ["displayName", "display_name", "nome_exibicao"])
    description = optional_str(item, ["description", "descricao"])
    is_default = as_bool(get_value(item, ["default", "padrao"], None))
    if display_name:
        payload["displayName"] = display_name
    if description:
        payload["description"] = description
    if is_default is not None:
        payload["default"] = is_default
    return payload


def persona_create_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
) -> dict[str, Any]:
    payload = base_persona_payload(item)
    domains = as_list(get_value(item, ["domain", "dominio", "domains", "dominios"], None))
    if domains:
        payload["domains"] = client.resolve_reference_names(domains, "domain")
    return payload


def persona_patch_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in base_persona_payload(item).items()
        if key not in {"name"}
    }
    domains = as_list(get_value(item, ["domain", "dominio", "domains", "dominios"], None))
    if domains:
        payload["domains"] = client.resolve_references(domains, "domain")
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

    default_roles = as_list(
        get_value(item, ["defaultRoles", "default_roles", "papeis_padrao"], None)
    )
    if default_roles:
        payload["defaultRoles"] = client.resolve_references(default_roles, "role")

    return payload


def user_name(item: Mapping[str, Any]) -> str:
    name = optional_str(item, ["name", "nome"])
    email = optional_str(item, ["email"])
    if not name and email:
        name = email.split("@", 1)[0]
    if not name:
        raise ValueError("Usuario precisa de name/nome ou email.")
    return name


def user_payload(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    *,
    for_patch: bool,
) -> dict[str, Any]:
    name = user_name(item)
    payload: dict[str, Any] = {"name": name}
    # O e-mail so e exigido para criar: o repositorio e publico e usuario
    # existente e identificado pelo nome, sem dado pessoal versionado.
    if not for_patch:
        email = optional_str(item, ["email"])
        if not email:
            raise ValueError(
                f"Usuario {name} nao existe na instancia e precisa de email "
                "para ser criado; use uma variavel, por exemplo "
                '"${USER_FULANO_EMAIL}".'
            )
        payload["email"] = email

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

    # A persona padrao e a que a interface usa para montar a tela da pessoa.
    default_persona = optional_str(
        item, ["defaultPersona", "default_persona", "persona_padrao"]
    )
    if default_persona:
        payload["defaultPersona"] = client.resolve_reference(default_persona, "persona")

    domains = as_list(get_value(item, ["domain", "dominio", "domains", "dominios"], None))
    if domains:
        if for_patch:
            payload["domains"] = client.resolve_references(domains, "domain")
        else:
            payload["domains"] = client.resolve_reference_names(domains, "domain")

    is_bot = as_bool(get_value(item, ["isBot", "is_bot"], None))
    is_admin = as_bool(get_value(item, ["isAdmin", "is_admin", "administrador"], None))
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
        client.patch_entity("domains", existing, payload, "domain")
        return

    payload = domain_create_payload(item, client, include_refs=include_refs)
    print(f"[domain] criando {name}")
    client.put_entity("domains", payload, "domain")


def create_or_patch_persona(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
) -> None:
    name = str(get_value(item, ["name", "nome"]))
    existing = client.get_by_name("persona", name, fields=["domains"])
    if existing:
        payload = persona_patch_payload(item, client)
        client.patch_entity("personas", existing, payload, "persona")
        return

    payload = persona_create_payload(item, client)
    print(f"[persona] criando {name}")
    client.put_entity("personas", payload, "persona")


def create_or_patch_team(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
    warnings: list[str],
    *,
    include_owners: bool,
) -> None:
    payload = team_payload(item, client, warnings, include_owners=include_owners)
    name = str(payload["name"])
    existing = client.get_by_name(
        "team", name, fields=["owners", "domains", "defaultRoles"]
    )
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
        client.patch_entity("teams", existing, mutable_payload, "team")
        return

    if "defaultRoles" in payload:
        payload["defaultRoles"] = [role["id"] for role in payload["defaultRoles"]]
    print(f"[team] criando {name}")
    client.post_entity("teams", payload, "team")


def create_or_patch_user(
    item: Mapping[str, Any],
    client: OpenMetadataClient,
) -> None:
    """Cria ou ajusta o usuario. A senha so e usada na criacao.

    Em usuario existente a senha nunca e tocada: reaplicar o YAML a cada merge
    resetaria a senha que a pessoa ja trocou. E a troca de senha de outro
    usuario (`/users/changePassword`) exige admin, que o bot do CI nao e; a
    senha inicial vai no proprio POST de criacao (`ADMIN_CREATE`), que o bot
    pode fazer.
    """
    name = user_name(item)
    existing = client.get_by_name(
        "user", name, fields=["teams", "personas", "domains", "roles", "defaultPersona"]
    )
    if existing:
        payload = user_payload(item, client, for_patch=True)
        mutable_payload = {key: value for key, value in payload.items() if key != "name"}
        client.patch_entity("users", existing, mutable_payload, "user")
        return

    payload = user_payload(item, client, for_patch=False)
    password = optional_str(item, ["password", "senha"])
    if password:
        payload["createPasswordType"] = "ADMIN_CREATE"
        payload["password"] = password
        payload["confirmPassword"] = optional_str(
            item, ["confirmPassword", "confirm_password", "confirmar_senha"], password
        )
    print(f"[user] criando {name}")
    # POST, e nao PUT: o create-or-update ignora a senha do payload.
    client.post_entity("users", payload, "user")


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
        client.patch_entity("dataProducts", existing, payload, "data_product")
        return

    payload = data_product_create_payload(item, client)
    print(f"[dataProduct] criando {name}")
    client.put_entity("dataProducts", payload, "data_product")


def apply_config(config: dict[str, Any], client: OpenMetadataClient) -> list[str]:
    validate_config_rules(config)
    warnings: list[str] = []
    domains = get_resource_items(config, ["domains", "dominios"], "domain")
    teams = get_resource_items(config, ["teams", "times", "time"], "team")
    personas = get_resource_items(config, ["personas"], "persona")
    users = get_resource_items(config, ["users", "usuarios"], "user")
    data_products = get_resource_items(
        config,
        ["data_products", "dataProducts", "produtos_dados", "produtos_de_dados"],
        "data_product",
    )

    # policy antes de role, role antes de time e usuario: cada um referencia
    # o anterior.
    for policy in get_resource_items(config, ["policies", "politicas"], "policy"):
        create_or_patch_policy(policy, client)

    for role in get_resource_items(config, ["roles", "papeis"], "role"):
        create_or_patch_role(role, client)

    for domain in domains:
        create_or_patch_domain(domain, client, include_refs=False)

    for persona in personas:
        create_or_patch_persona(persona, client)

    for team in teams:
        create_or_patch_team(team, client, warnings, include_owners=False)

    for user in users:
        create_or_patch_user(user, client)

    for domain in domains:
        if has_value(domain, ["owners", "proprietarios"]) or has_value(
            domain, ["experts", "especialistas"]
        ):
            create_or_patch_domain(domain, client, include_refs=True)

    for team in teams:
        create_or_patch_team(team, client, warnings, include_owners=True)

    for data_product in data_products:
        create_or_patch_data_product(data_product, client)

    for subscription in get_resource_items(
        config, ["event_subscriptions", "alertas"], "event_subscription"
    ):
        create_or_patch_event_subscription(subscription, client, warnings)

    return warnings

