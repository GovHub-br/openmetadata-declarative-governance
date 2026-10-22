from __future__ import annotations

from typing import Any

from .utils import get_resource_items, get_value, has_value, parse_reference


def validate_owner_specs(
    owners: Any,
    default_type: str,
    resource_name: str,
) -> str | None:
    specs = [parse_reference(owner, default_type) for owner in as_list(owners)]
    if len(specs) > 1 and any(spec.entity_type == "team" for spec in specs):
        owners_label = ", ".join(
            f"{spec.entity_type}:{spec.name}" for spec in specs
        )
        return (
            f"{resource_name}: OpenMetadata aceita um unico owner do tipo team. "
            f"Para multiplos owners, use apenas usuarios. Owners recebidos: "
            f"{owners_label}"
        )
    return None


def validate_password_spec(password: str, resource_name: str) -> str | None:
    has_upper = any(char.isupper() for char in password)
    has_lower = any(char.islower() for char in password)
    has_digit = any(char.isdigit() for char in password)
    has_special = any(not char.isalnum() for char in password)
    if 8 <= len(password) <= 56 and has_upper and has_lower and has_digit and has_special:
        return None
    return (
        f"{resource_name}: senha deve ter 8 a 56 caracteres, com ao menos "
        "uma maiuscula, uma minuscula, um digito e um caractere especial."
    )


def validate_config_rules(config: dict[str, Any]) -> None:
    domains = get_resource_items(config, ["domains", "dominios"], "domain")
    users = get_resource_items(config, ["users", "usuarios"], "user")
    personas = get_resource_items(config, ["personas"], "persona")
    data_products = get_resource_items(
        config,
        ["data_products", "dataProducts", "produtos_dados", "produtos_de_dados"],
        "data_product",
    )

    errors: list[str] = []
    for policy in get_resource_items(config, ["policies", "politicas"], "policy"):
        name = get_value(policy, ["name", "nome"], "<sem nome>")
        rules = as_list(get_value(policy, ["rules", "regras"], None))
        if not rules:
            errors.append(f"policy {name}: precisa de ao menos uma regra.")
        for rule in rules:
            rule = {str(k).lower(): v for k, v in rule.items()}
            effect = str(rule.get("efeito") or rule.get("effect") or "").lower()
            if effect not in {"allow", "deny"}:
                errors.append(f"policy {name}: efeito deve ser allow ou deny.")
            if not (rule.get("recursos") or rule.get("resources")):
                errors.append(f"policy {name}: regra sem recursos.")
            if not (rule.get("operacoes") or rule.get("operations")):
                errors.append(f"policy {name}: regra sem operacoes.")

    external = {str(name) for name in config.get("dominios_externos") or []}
    for domain in domains:
        name = str(get_value(domain, ["name", "nome"], "<sem nome>"))
        parent = get_value(domain, ["parent", "parentDomain", "dominio_pai"], None)
        root = str(parent or name).split(".", 1)[0]
        if root in external:
            errors.append(
                f"domain {name}: a hierarquia {root} e mantida por outro "
                "repositorio (dominios_externos); aqui ela so pode ser referenciada."
            )

    for data_product in data_products:
        name = str(get_value(data_product, ["name", "nome"], "<sem nome>"))
        for domain in as_list(
            get_value(data_product, ["domain", "dominio", "domains", "dominios"], None)
        ):
            if str(domain).split(".", 1)[0] in external:
                errors.append(
                    f"data_product {name}: o dominio {domain} e mantido por outro "
                    "repositorio (dominios_externos)."
                )

    for domain in domains:
        if has_value(domain, ["owners", "proprietarios"]):
            name = get_value(domain, ["name", "nome"], "<sem nome>")
            error = validate_owner_specs(
                get_value(domain, ["owners", "proprietarios"]),
                "team",
                f"domain {name}",
            )
            if error:
                errors.append(error)

    for user in users:
        if has_value(user, ["password", "senha"]):
            name = get_value(user, ["name", "nome"], "<sem nome>")
            password = str(get_value(user, ["password", "senha"]))
            error = validate_password_spec(password, f"user {name}")
            if error:
                errors.append(error)

    for persona in personas:
        if has_value(persona, ["owners", "proprietarios"]):
            name = get_value(persona, ["name", "nome"], "<sem nome>")
            errors.append(
                f"persona {name}: persona nao tem proprietarios no OpenMetadata "
                "(a API recusa o campo owners)."
            )

    for data_product in data_products:
        if has_value(data_product, ["owners", "proprietarios"]):
            name = get_value(data_product, ["name", "nome"], "<sem nome>")
            error = validate_owner_specs(
                get_value(data_product, ["owners", "proprietarios"]),
                "team",
                f"data_product {name}",
            )
            if error:
                errors.append(error)

    if errors:
        formatted_errors = "\n- ".join(errors)
        raise ValueError(f"Config invalida:\n- {formatted_errors}")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]

