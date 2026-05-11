from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

from .audit import AuditLogger
from .client import OpenMetadataClient
from .config import read_config
from .errors import OpenMetadataError
from .reconciler import apply_config
from .validation import validate_config_rules


DEFAULT_RESOURCE_PATH = str(Path(__file__).resolve().parents[1] / "resources")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upsert declarativo de dominios, times, usuarios e produtos."
    )
    parser.add_argument(
        "-f",
        "--file",
        default=os.getenv("OPENMETADATA_RESOURCE_FILE", DEFAULT_RESOURCE_PATH),
        help="Arquivo YAML ou diretorio modular de recursos.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("OM_HOST"),
        help="URL do OpenMetadata. Tambem aceita OM_HOST.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("OM_TOKEN"),
        help="Token JWT/PAT. Tambem aceita OM_TOKEN.",
    )
    parser.add_argument(
        "--audit-log",
        default=os.getenv("OM_AUDIT_LOG", "/tmp/om_apply_audit.jsonl"),
        help="Arquivo JSONL para registrar erros da API.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra as chamadas mutantes sem enviar para o OpenMetadata.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Valida o YAML e sai sem chamar a API.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    try:
        resource_path = Path(args.file)
        if not resource_path.exists():
            raise ValueError(
                f"Arquivo/diretorio de resources nao encontrado: {args.file}. "
                "Monte a pasta no container com -v ...:/data/resources:ro "
                "ou use sh openmetadata_script/run.sh."
            )
        config = read_config(args.file)
        if args.validate_only:
            validate_config_rules(config)
            print("Config valida.")
            return 0

        if not args.host:
            print("Erro: informe --host ou OM_HOST.", file=sys.stderr)
            return 2
        if not args.token:
            print("Erro: informe --token ou OM_TOKEN.", file=sys.stderr)
            return 2

        client = OpenMetadataClient(
            host=args.host,
            token=args.token,
            timeout=args.timeout,
            dry_run=args.dry_run,
            audit=AuditLogger(args.audit_log),
        )
        warnings = apply_config(config, client)
    except (OSError, ValueError, requests.RequestException, OpenMetadataError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    for warning in warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    print("Concluido.")
    return 0
