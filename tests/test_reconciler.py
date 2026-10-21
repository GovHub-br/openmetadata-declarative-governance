from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from om_apply.client import OpenMetadataClient
from om_apply.config import read_config
from om_apply.errors import OpenMetadataError
from om_apply.export import export_resources
from om_apply.reconciler import apply_config

from .fake_om import API, FakeOpenMetadata


@pytest.fixture
def om() -> FakeOpenMetadata:
    om = FakeOpenMetadata()
    om.add("users", name="ana", displayName="Ana", isAdmin=True, email="ana@x.org")
    om.add("users", name="beto", email="beto@x.org")
    om.add("users", name="ingestion-bot", isBot=True, email="bot@x.org")
    om.add("users", name="admin", isAdmin=True, email="admin@x.org")
    om.add("roles", name="DataSteward")
    om.add("personas", name="data-engineer", displayName="Engenheiro(a) de Dados", default=False)

    om.add("teams", name="Organization", teamType="Organization")
    ipea = om.add(
        "teams",
        name="ipea-data-engineering",
        displayName="Time do IPEA",
        teamType="Group",
        email="dados-ipea@example.org",
        isJoinable=True,
    )
    om.add("teams", name="mcid-data-engineering", teamType="Group", isJoinable=True)

    contratos = om.add(
        "domains",
        name="contratos",
        displayName="Contratos",
        domainType="Aggregate",
        description="Contratos e execucao contratual.",
        owners=[om.ref("teams", "ipea-data-engineering")],
        experts=[om.ref("users", "beto")],
    )
    om.add("domains", name="ted", domainType="Aggregate", owners=[om.ref("teams", "ipea-data-engineering")])
    mcid = om.add("domains", name="MCid", domainType="Aggregate")
    om.add("domains", name="Habitacao", domainType="Aggregate", parent=om.ref("domains", "MCid"))

    ipea["domains"] = [om.ref("domains", "contratos")]
    ana = om.find("users", "ana")
    ana.update(
        teams=[om.ref("teams", "ipea-data-engineering"), om.ref("teams", "mcid-data-engineering")],
        personas=[om.ref("personas", "data-engineer")],
        roles=[om.ref("roles", "DataSteward")],
        domains=[om.ref("domains", "contratos"), om.ref("domains", "ted"), om.ref("domains", "MCid")],
    )

    om.add(
        "dataProducts",
        name="contratos",
        domains=[om.ref("domains", "contratos")],
        owners=contratos["owners"],
        experts=[],
    )
    om.add("dataProducts", name="conjuntura", domains=[om.ref("domains", "MCid.Habitacao")])
    assert mcid
    return om


def client_for(om: FakeOpenMetadata, dry_run: bool = False) -> OpenMetadataClient:
    client = OpenMetadataClient(host=API, token="t", timeout=1, dry_run=dry_run, audit=None)
    client.session = om
    return client


def write_resources(directory: Path, **files: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (directory / f"{name}.yml").write_text(yaml.safe_dump(body, allow_unicode=True))
    return directory


def test_export_seguido_de_apply_nao_altera_nada(om: FakeOpenMetadata, tmp_path: Path) -> None:
    resources = write_resources(tmp_path, domains={"dominios_externos": ["MCid"], "domains": []})

    export_resources(client_for(om), str(resources))
    client = client_for(om)
    apply_config(read_config(str(resources)), client)

    assert om.mutations == []
    # 2 dominios (2 passadas), 1 persona, 2 times (2 passadas), 2 usuarios, 1 produto
    assert client.counts == {"criados": 0, "atualizados": 0, "sem_mudanca": 12}


def test_export_deixa_de_fora_externos_bots_admin_e_email(om: FakeOpenMetadata, tmp_path: Path) -> None:
    resources = write_resources(tmp_path, domains={"dominios_externos": ["MCid"], "domains": []})
    export_resources(client_for(om), str(resources))

    domains = yaml.safe_load((resources / "domains.yml").read_text())
    users = yaml.safe_load((resources / "users.yml").read_text())["users"]
    teams = yaml.safe_load((resources / "teams.yml").read_text())["times"]
    products = yaml.safe_load((resources / "data_products.yml").read_text())["data_products"]

    assert domains["dominios_externos"] == ["MCid"]
    assert [d["nome"] for d in domains["domains"]] == ["contratos", "ted"]
    assert [u["nome"] for u in users] == ["ana", "beto"]
    assert not any("email" in u for u in users)
    assert users[0]["dominios"] == ["MCid", "contratos", "ted"]
    assert "Organization" not in [t["nome"] for t in teams]
    # produto herda owner do dominio, mas o expert diverge e fica explicito
    assert products == [
        {
            "nome": "contratos",
            "dominio": "contratos",
            "inherit_from_domain": True,
            "especialistas": [],
        }
    ]


def test_patch_envia_so_o_campo_que_mudou(om: FakeOpenMetadata, tmp_path: Path) -> None:
    resources = write_resources(
        tmp_path,
        domains={
            "domains": [
                {
                    "nome": "contratos",
                    "nome_exibicao": "Contratos",
                    "tipo_dominio": "Aggregate",
                    "descricao": "Descricao nova.",
                    "proprietarios": ["ipea-data-engineering"],
                    "especialistas": ["beto"],
                }
            ]
        },
    )
    apply_config(read_config(str(resources)), client_for(om))

    assert [(m, ep, [op["path"] for op in body]) for m, ep, body in om.mutations] == [
        ("PATCH", "domains", ["/description"])
    ]


def test_dry_run_le_a_instancia_e_nao_escreve(om: FakeOpenMetadata, tmp_path: Path, capsys) -> None:
    resources = write_resources(
        tmp_path,
        domains={"domains": [{"nome": "contratos", "descricao": "Outra."}, {"nome": "novo"}]},
    )
    client = client_for(om, dry_run=True)
    apply_config(read_config(str(resources)), client)

    out = capsys.readouterr().out
    assert om.mutations == []
    assert "[domain] contratos: atualizando" in out
    assert "[domain] criando novo" in out
    assert client.counts == {"criados": 1, "atualizados": 1, "sem_mudanca": 0}


def test_usuario_com_varios_dominios_nao_perde_nenhum(om: FakeOpenMetadata, tmp_path: Path) -> None:
    resources = write_resources(
        tmp_path,
        users={"users": [{"nome": "ana", "dominios": ["contratos", "ted", "MCid"]}]},
    )
    apply_config(read_config(str(resources)), client_for(om))

    assert om.mutations == []


def test_usuario_existente_dispensa_email_e_novo_exige(om: FakeOpenMetadata, tmp_path: Path) -> None:
    existing = write_resources(tmp_path / "a", users={"users": [{"nome": "beto", "times": ["ipea-data-engineering"]}]})
    apply_config(read_config(str(existing)), client_for(om))
    assert [(m, ep) for m, ep, _ in om.mutations] == [("PATCH", "users")]

    new = write_resources(tmp_path / "b", users={"users": [{"nome": "carla", "email": "${CARLA_EMAIL}"}]})
    with pytest.raises(ValueError, match="precisa de email"):
        apply_config(read_config(str(new)), client_for(om))


def test_hierarquia_externa_nao_pode_ser_declarada(tmp_path: Path) -> None:
    resources = write_resources(
        tmp_path,
        domains={
            "dominios_externos": ["MCid"],
            "domains": [{"nome": "Saneamento", "dominio_pai": "MCid"}],
        },
        data_products={"data_products": [{"nome": "x", "dominio": "MCid.Habitacao"}]},
    )
    with pytest.raises(ValueError) as erro:
        apply_config(read_config(str(resources)), client_for(FakeOpenMetadata()))
    assert "domain Saneamento" in str(erro.value)
    assert "data_product x" in str(erro.value)


def test_referencia_inexistente_falha_tambem_no_dry_run(om: FakeOpenMetadata, tmp_path: Path) -> None:
    resources = write_resources(
        tmp_path, domains={"domains": [{"nome": "contratos", "proprietarios": ["time-que-nao-existe"]}]}
    )
    with pytest.raises(OpenMetadataError, match="time-que-nao-existe"):
        apply_config(read_config(str(resources)), client_for(om, dry_run=True))


def test_dry_run_nao_imprime_email(om: FakeOpenMetadata, tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("CARLA_EMAIL", "carla@pessoal.com")
    resources = write_resources(tmp_path, users={"users": [{"nome": "carla", "email": "${CARLA_EMAIL}"}]})
    apply_config(read_config(str(resources)), client_for(om, dry_run=True))

    out = capsys.readouterr().out
    assert "[user] criando carla" in out
    assert "carla@pessoal.com" not in out
