#!/usr/bin/env python
"""Bootstrap glossary terms and structured metadata into Weaviate for the PoC.

Usage:
    python internal_poc/scripts/ingest_sample_data.py --source internal_poc/data

Requirements:
    - `pip install -e .` at repo root (provides weaviate client + dependencies)
    - Running Weaviate instance reachable via `WEAVIATE_URL_VERBA`
"""

import argparse
import csv
import os
from pathlib import Path

from dotenv import load_dotenv
import weaviate
from urllib.parse import urlparse

from weaviate.auth import AuthApiKey
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.init import AdditionalConfig, Timeout

GLOSSARY_CLASS = "GlossaryTerm"


def load_env(env_file: Path | None) -> None:
    if env_file:
        if not env_file.exists():
            raise FileNotFoundError(f"Env file not found: {env_file}")
        load_dotenv(dotenv_path=env_file)
    else:
        load_dotenv()


def _resolve_connection_params(url: str) -> tuple[str, int, bool, int]:
    """Derive host/port/security flags from a Weaviate URL."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"Invalid WEAVIATE_URL_VERBA value: {url}")

    secure = parsed.scheme == "https"
    http_port = parsed.port or (443 if secure else 80)
    # gRPC typically uses 50051 for HTTP deployments and 443 for HTTPS
    grpc_port = 443 if secure else 50051
    return parsed.hostname, http_port, secure, grpc_port


def get_client():
    url = os.getenv("WEAVIATE_URL_VERBA")
    api_key = os.getenv("WEAVIATE_API_KEY_VERBA")
    if not url:
        raise ValueError("WEAVIATE_URL_VERBA is not set")

    host, http_port, secure, grpc_port = _resolve_connection_params(url)

    additional_config = AdditionalConfig(timeout=Timeout(init=60, query=60, insert=120))

    auth = AuthApiKey(api_key) if api_key else None

    # Local OSS deployments expose HTTP without TLS; use convenience helper.
    if not secure and host in {"localhost", "127.0.0.1"}:
        return weaviate.connect_to_local(
            host=host,
            port=http_port,
            grpc_port=grpc_port,
            additional_config=additional_config,
            skip_init_checks=True,
            auth_credentials=auth,
        )

    return weaviate.connect_to_custom(
        http_host=host,
        http_port=http_port,
        http_secure=secure,
        grpc_host=host,
        grpc_port=grpc_port,
        grpc_secure=secure,
        auth_credentials=auth,
        additional_config=additional_config,
        skip_init_checks=True,
    )


def ensure_glossary_schema(client) -> None:
    if client.collections.exists(GLOSSARY_CLASS):
        return

    client.collections.create(
        name=GLOSSARY_CLASS,
        description="Domain glossary terms for manufacturing PoC",
        vectorizer_config=Configure.Vectorizer.none(),
        properties=[
            Property(name="term", data_type=DataType.TEXT, description="Canonical term"),
            Property(name="definition", data_type=DataType.TEXT, description="Definition or expansion"),
            Property(name="product_context", data_type=DataType.TEXT, description="Product family or process area"),
            Property(name="effective_date", data_type=DataType.DATE, description="Date the definition became valid"),
            Property(name="version", data_type=DataType.INT, description="Change control version"),
        ],
    )


def ingest_glossary(client, glossary_path: Path) -> int:
    if not glossary_path.exists():
        raise FileNotFoundError(f"Glossary file not found: {glossary_path}")

    with glossary_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Glossary CSV missing header row")

        rows = [
            {
                "term": row.get("term", "").strip(),
                "definition": row.get("definition", "").strip(),
                "product_context": row.get("product_context", "").strip(),
                "effective_date": row.get("effective_date", "").strip() or None,
                "version": int(row["version"]) if row.get("version") else None,
            }
            for row in reader
            if row.get("term")
        ]

    if not rows:
        return 0

    collection = client.collections.get(GLOSSARY_CLASS)

    with collection.batch.dynamic() as batch:
        for obj in rows:
            batch.add_object(properties=obj)

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manufacturing PoC bootstrapper")
    parser.add_argument(
        "--source",
        default="internal_poc/data",
        help="Root directory that holds glossary and reference files",
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Optional path to .env file with Weaviate credentials",
    )
    args = parser.parse_args()

    load_env(Path(args.env_file) if args.env_file else None)
    client = get_client()
    try:
        ensure_glossary_schema(client)
        glossary_file = Path(args.source) / "glossary" / "glossary_sample.csv"
        inserted = ingest_glossary(client, glossary_file)
        print(f"Inserted {inserted} glossary terms into class {GLOSSARY_CLASS}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
