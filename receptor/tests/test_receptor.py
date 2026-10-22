from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
import requests

from receptor import receptor

SEGREDO = "segredo-de-teste"
ROTAS = {"Cidades": "GovHub-br/data-application-cidades"}
TABELA = "Cidades.cidades.ouro.ouro_far_ficha_empreendimento"


class GitHubDeTeste:
    def __init__(self, falhar: bool = False) -> None:
        self.disparos: list[tuple[str, dict]] = []
        self.falhar = falhar

    def disparar(self, repositorio: str, carga: dict) -> None:
        if self.falhar:
            raise requests.ConnectionError("fora do ar")
        self.disparos.append((repositorio, carga))


def evento(
    about: str = f"<#E::table::{TABELA}::description>",
    tipo_task: str = "UpdateDescription",
    sugestao: str = "Uma linha por empreendimento FAR.",
    tipo_evento: str = "threadCreated",
    tipo_thread: str = "Task",
) -> bytes:
    """ChangeEvent como o OpenMetadata 1.13 envia: `entity` e string JSON."""
    thread = {
        "id": "8f1c0000-0000-0000-0000-000000000001",
        "type": tipo_thread,
        "about": about,
        "createdBy": "especialista",
        "message": "Sugestao de descricao",
        "task": {
            "id": 42,
            "type": tipo_task,
            "status": "Open",
            "oldValue": "",
            "suggestion": sugestao,
            "assignees": [{"id": "t1", "type": "team", "name": "mcid-data-engineering"}],
        },
    }
    return json.dumps(
        {
            "eventType": tipo_evento,
            "entityType": "THREAD",
            "entityId": thread["id"],
            "userName": "especialista",
            "timestamp": 1792000000000,
            "entity": json.dumps(thread),
        }
    ).encode()


def assinar(corpo: bytes, segredo: str = SEGREDO) -> str:
    digest = hmac.new(segredo.encode(), corpo, hashlib.sha256).digest()
    return "sha256=" + base64.b64encode(digest).decode()


def tratar(corpo: bytes, github: GitHubDeTeste, assinatura: str | None = None):
    return receptor.tratar(corpo, assinatura or assinar(corpo), SEGREDO, ROTAS, github)


def test_sugestao_de_tabela_vira_dispatch_no_repo_do_servico() -> None:
    github = GitHubDeTeste()
    assert tratar(evento(), github) == (202, "disparado")
    assert github.disparos == [
        (
            "GovHub-br/data-application-cidades",
            {
                "task_id": 42,
                "thread_id": "8f1c0000-0000-0000-0000-000000000001",
                "tipo": "table",
                "fqn": TABELA,
                "coluna": None,
                "sugestao": "Uma linha por empreendimento FAR.",
                "autor": "especialista",
            },
        )
    ]


def test_sugestao_de_coluna_leva_o_nome_da_coluna() -> None:
    github = GitHubDeTeste()
    tratar(evento(about=f"<#E::table::{TABELA}::columns::apf::description>"), github)
    assert github.disparos[0][1]["coluna"] == "apf"


def test_assinatura_errada_ou_ausente_e_recusada() -> None:
    github = GitHubDeTeste()
    corpo = evento()
    assert receptor.tratar(corpo, assinar(corpo, "outro"), SEGREDO, ROTAS, github)[0] == 401
    assert receptor.tratar(corpo, None, SEGREDO, ROTAS, github)[0] == 401
    assert github.disparos == []


@pytest.mark.parametrize(
    "corpo",
    [
        evento(tipo_evento="threadUpdated"),
        evento(tipo_evento="taskClosed"),
        evento(tipo_thread="Conversation"),
        evento(tipo_task="RequestDescription", sugestao=""),
        evento(tipo_task="UpdateTag"),
        evento(about=f"<#E::table::{TABELA}::tags>"),
    ],
    ids=["edicao", "fechamento", "conversa", "pedido-sem-texto", "tag", "outro-campo"],
)
def test_o_que_nao_e_sugestao_de_descricao_nova_e_ignorado(corpo: bytes) -> None:
    github = GitHubDeTeste()
    assert tratar(corpo, github) == (200, "ignorado")
    assert github.disparos == []


def test_servico_sem_rota_e_ignorado() -> None:
    github = GitHubDeTeste()
    corpo = evento(about="<#E::table::MinC.minc.agentes.x::description>")
    assert tratar(corpo, github) == (200, "servico sem rota")
    assert github.disparos == []


def test_falha_no_github_pede_nova_tentativa() -> None:
    assert tratar(evento(), GitHubDeTeste(falhar=True)) == (502, "falha no GitHub")


def test_fqn_com_nome_entre_aspas() -> None:
    assert receptor.separar_fqn('Cidades.cidades."ouro.x".tabela') == [
        "Cidades",
        "cidades",
        "ouro.x",
        "tabela",
    ]


def test_github_app_assina_jwt_e_reaproveita_o_token(monkeypatch) -> None:
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = chave.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    chamadas: list[tuple[str, str]] = []

    class Resposta:
        def __init__(self, corpo: dict) -> None:
            self.corpo = corpo

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return self.corpo

    def get(url, headers, timeout):
        emitido = jwt.decode(
            headers["Authorization"].removeprefix("Bearer "),
            chave.public_key(),
            algorithms=["RS256"],
        )
        assert emitido["iss"] == "123"
        chamadas.append(("GET", url))
        return Resposta({"id": 9})

    def post(url, headers, timeout, json=None):
        chamadas.append(("POST", url))
        return Resposta({"token": "ghs_x"})

    monkeypatch.setattr(receptor.requests, "get", get)
    monkeypatch.setattr(receptor.requests, "post", post)
    app = receptor.GitHubApp("123", pem)

    assert app.token("GovHub-br/x") == "ghs_x"
    assert app.token("GovHub-br/x") == "ghs_x"
    assert chamadas == [
        ("GET", "https://api.github.com/repos/GovHub-br/x/installation"),
        ("POST", "https://api.github.com/app/installations/9/access_tokens"),
    ]
