"""Receptor de sugestoes do OpenMetadata.

Recebe o webhook do OpenMetadata e, quando alguem cria uma Task de sugestao de
descricao, dispara um `repository_dispatch` no repositorio dono do ativo. O
resto (editar o YAML, abrir o PR, fechar a Task) e do GitHub Actions de la.

E burro de proposito: nao guarda estado, nao fala com banco e nao decide nada
alem de "isto e uma sugestao de descricao de um servico que eu conheco?".

Variaveis de ambiente:
    OM_WEBHOOK_SECRET        segredo do alerta no OpenMetadata (assinatura HMAC)
    ROTAS                    JSON servico -> repositorio, ex.:
                             {"Cidades": "GovHub-br/data-application-cidades"}
    GITHUB_APP_ID            id do GitHub App que dispara o evento
    GITHUB_APP_PRIVATE_KEY   chave privada (PEM) do App
    PORT                     porta HTTP (padrao 8080)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
import requests

LOG = logging.getLogger("receptor")
GITHUB_API = "https://api.github.com"
EVENTO_GITHUB = "om-sugestao-descricao"
# O OpenMetadata cria UpdateDescription quando o ativo ja tem descricao e
# RequestDescription quando esta vazia; as duas carregam o texto sugerido.
TASKS_DE_DESCRICAO = {"UpdateDescription", "RequestDescription"}


# ── o que chega do OpenMetadata ─────────────────────────────────────────────
def assinatura_valida(segredo: str, corpo: bytes, cabecalho: str | None) -> bool:
    """`X-OM-Signature: sha256=<base64(HMAC-SHA256(segredo, corpo))>`."""
    if not segredo or not cabecalho:
        return False
    esperado = "sha256=" + base64.b64encode(
        hmac.new(segredo.encode(), corpo, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(esperado, cabecalho)


def separar_fqn(fqn: str) -> list[str]:
    """Partes do FQN; nome com ponto vem entre aspas (`"a.b"`) e fica inteiro."""
    partes, atual, entre_aspas = [], "", False
    for char in fqn:
        if char == '"':
            entre_aspas = not entre_aspas
        elif char == "." and not entre_aspas:
            partes.append(atual)
            atual = ""
            continue
        atual += char
    partes.append(atual)
    return [parte.strip('"') for parte in partes]


def ler_about(about: str) -> dict[str, str | None] | None:
    """`<#E::table::<fqn>::description>` ou `...::columns::<coluna>::description>`."""
    if not (about.startswith("<#E::") and about.endswith(">")):
        return None
    partes = about[len("<#E::") : -1].split("::")
    if len(partes) < 3 or partes[-1] != "description":
        return None
    tipo, fqn = partes[0], partes[1]
    coluna = None
    if len(partes) == 5 and partes[2] == "columns":
        coluna = partes[3]
    elif len(partes) != 3:
        return None
    return {"tipo": tipo, "fqn": fqn, "coluna": coluna}


def sugestao_do_evento(evento: dict[str, Any]) -> dict[str, Any] | None:
    """Sugestao de descricao aberta agora, ou None para qualquer outro evento.

    O alerta de Task dispara em todo evento da thread (comentario, fechamento,
    edicao); so a criacao vira PR.
    """
    if evento.get("entityType") != "THREAD" or evento.get("eventType") != "threadCreated":
        return None
    thread = evento.get("entity")
    if isinstance(thread, str):
        thread = json.loads(thread)
    if not isinstance(thread, dict) or thread.get("type") != "Task":
        return None
    task = thread.get("task") or {}
    if task.get("type") not in TASKS_DE_DESCRICAO or task.get("status", "Open") != "Open":
        return None
    if not (task.get("suggestion") or "").strip():
        return None
    alvo = ler_about(thread.get("about") or "")
    if not alvo:
        return None
    return {
        "task_id": task.get("id"),
        "thread_id": thread.get("id"),
        "tipo": alvo["tipo"],
        "fqn": alvo["fqn"],
        "coluna": alvo["coluna"],
        "sugestao": task["suggestion"].strip(),
        "autor": thread.get("createdBy"),
    }


def repositorio_do_ativo(fqn: str, rotas: dict[str, str]) -> str | None:
    """O servico (primeira parte do FQN) decide o repositorio dono."""
    return rotas.get(separar_fqn(fqn)[0])


# ── GitHub App ──────────────────────────────────────────────────────────────
class GitHubApp:
    def __init__(self, app_id: str, chave_privada: str) -> None:
        self.app_id = app_id
        self.chave_privada = chave_privada
        self._tokens: dict[str, tuple[str, float]] = {}

    def _jwt(self) -> str:
        agora = int(time.time())
        return jwt.encode(
            {"iat": agora - 60, "exp": agora + 540, "iss": self.app_id},
            self.chave_privada,
            algorithm="RS256",
        )

    def token(self, repositorio: str) -> str:
        """Token de instalacao do App no repositorio, reaproveitado ate expirar."""
        guardado = self._tokens.get(repositorio)
        if guardado and guardado[1] > time.time() + 60:
            return guardado[0]
        cabecalhos = {
            "Authorization": f"Bearer {self._jwt()}",
            "Accept": "application/vnd.github+json",
        }
        instalacao = requests.get(
            f"{GITHUB_API}/repos/{repositorio}/installation", headers=cabecalhos, timeout=15
        )
        instalacao.raise_for_status()
        resposta = requests.post(
            f"{GITHUB_API}/app/installations/{instalacao.json()['id']}/access_tokens",
            headers=cabecalhos,
            timeout=15,
        )
        resposta.raise_for_status()
        token = resposta.json()["token"]
        # tokens de instalacao valem uma hora
        self._tokens[repositorio] = (token, time.time() + 3300)
        return token

    def disparar(self, repositorio: str, carga: dict[str, Any]) -> None:
        resposta = requests.post(
            f"{GITHUB_API}/repos/{repositorio}/dispatches",
            headers={
                "Authorization": f"Bearer {self.token(repositorio)}",
                "Accept": "application/vnd.github+json",
            },
            json={"event_type": EVENTO_GITHUB, "client_payload": carga},
            timeout=15,
        )
        resposta.raise_for_status()


# ── HTTP ────────────────────────────────────────────────────────────────────
def tratar(
    corpo: bytes,
    assinatura: str | None,
    segredo: str,
    rotas: dict[str, str],
    github: GitHubApp,
) -> tuple[int, str]:
    """Decide a resposta ao OpenMetadata. Separado do servidor para ser testado."""
    if not assinatura_valida(segredo, corpo, assinatura):
        return 401, "assinatura invalida"
    try:
        evento = json.loads(corpo)
    except json.JSONDecodeError:
        return 400, "corpo nao e JSON"
    sugestao = sugestao_do_evento(evento)
    if not sugestao:
        return 200, "ignorado"
    repositorio = repositorio_do_ativo(sugestao["fqn"], rotas)
    if not repositorio:
        LOG.info("sugestao em servico sem rota: %s", sugestao["fqn"])
        return 200, "servico sem rota"
    try:
        github.disparar(repositorio, sugestao)
    except requests.RequestException as erro:
        # 502 faz o OpenMetadata tentar de novo; o Action e idempotente pela
        # branch `om-sugestao/<task_id>`, entao repetir nao duplica PR.
        LOG.warning("falha ao disparar em %s: %s", repositorio, erro)
        return 502, "falha no GitHub"
    LOG.info("task %s -> %s (%s)", sugestao["task_id"], repositorio, sugestao["fqn"])
    return 202, "disparado"


def servidor(segredo: str, rotas: dict[str, str], github: GitHubApp, porta: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _responder(self, status: int, texto: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(texto.encode())

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/saude":
                self._responder(200, "ok")
            else:
                self._responder(404, "nao encontrado")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/openmetadata":
                self._responder(404, "nao encontrado")
                return
            tamanho = int(self.headers.get("Content-Length") or 0)
            corpo = self.rfile.read(tamanho)
            status, texto = tratar(
                corpo, self.headers.get("X-OM-Signature"), segredo, rotas, github
            )
            self._responder(status, texto)

        def log_message(self, formato: str, *args: Any) -> None:
            LOG.debug(formato, *args)

    return ThreadingHTTPServer(("0.0.0.0", porta), Handler)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    segredo = os.environ["OM_WEBHOOK_SECRET"]
    rotas = json.loads(os.environ["ROTAS"])
    github = GitHubApp(os.environ["GITHUB_APP_ID"], os.environ["GITHUB_APP_PRIVATE_KEY"])
    porta = int(os.environ.get("PORT", "8080"))
    LOG.info("receptor na porta %s; rotas: %s", porta, ", ".join(sorted(rotas)))
    servidor(segredo, rotas, github, porta).serve_forever()


if __name__ == "__main__":
    main()
