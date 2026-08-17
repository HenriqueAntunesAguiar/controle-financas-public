"""Adaptador de publicacao de versoes no PostgreSQL."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi_app.domain import ConnectionStatus, ImportReceipt
from fastapi_app.infrastructure.config import PostgresSettings


class PostgresVersionPublisher:
    component = "postgresql"

    def __init__(self, settings: PostgresSettings):
        self.settings = settings
        self.schema_path = Path(__file__).with_name("postgres_schema.sql")

    def _connect(self, timeout: int | None = None):
        import psycopg

        return psycopg.connect(
            host=self.settings.host,
            port=self.settings.port,
            dbname=self.settings.database,
            user=self.settings.user,
            password=self.settings.password,
            connect_timeout=timeout or self.settings.connect_timeout,
        )

    def _schema_statements(self) -> list[str]:
        return [
            statement.strip()
            for statement in self.schema_path.read_text(encoding="utf-8").split(";")
            if statement.strip()
        ]

    def _apply_schema(self, cursor: Any) -> None:
        for statement in self._schema_statements():
            cursor.execute(statement)

    def migrate(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._apply_schema(cursor)

    def publish(self, payload: dict[str, Any]) -> ImportReceipt:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                self._apply_schema(cursor)
                cursor.execute(
                    "INSERT INTO financeiro.documentos_fatura(id, nome) VALUES (%s, %s) "
                    "ON CONFLICT(id) DO UPDATE SET nome=EXCLUDED.nome",
                    (payload["documento_id"], payload["nome"]),
                )
                cursor.execute(
                    """
                    INSERT INTO financeiro.versoes_fatura(
                        documento_id, numero_versao, conteudo_hash,
                        data_referencia, quantidade_transacoes, status_qualidade,
                        total_extraido, total_lancamentos_pdf, criado_em
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(conteudo_hash) DO NOTHING RETURNING id
                    """,
                    (
                        payload["documento_id"],
                        payload["numero_versao"],
                        payload["conteudo_hash"],
                        payload["data_referencia"],
                        len(payload["transacoes"]),
                        payload.get("qualidade", {}).get("status", "legacy"),
                        payload.get("qualidade", {}).get("total_extraido"),
                        payload.get("qualidade", {}).get("total_lancamentos_pdf"),
                        payload["gerado_em"],
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    cursor.execute(
                        "SELECT id FROM financeiro.versoes_fatura WHERE conteudo_hash=%s",
                        (payload["conteudo_hash"],),
                    )
                    return ImportReceipt(int(cursor.fetchone()[0]), True)
                version_id = int(inserted[0])
                cursor.executemany(
                    """
                    INSERT INTO financeiro.transacoes_versao(
                        versao_id, numero_linha, data_transacao, valor, tipo,
                        categoria, descricao, descricao_normalizada, localidade,
                        estabelecimento_id, parcela_atual, total_parcelas, pagina_origem
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    [
                        (
                            version_id,
                            index,
                            transaction["data_iso"],
                            transaction["valor"],
                            transaction["tipo"],
                            transaction["categoria"],
                            transaction.get("descricao", "Descricao indisponivel"),
                            str(
                                transaction.get(
                                    "descricao_normalizada",
                                    transaction.get(
                                        "descricao", "descricao indisponivel"
                                    ),
                                )
                            ).upper(),
                            transaction.get("localidade"),
                            transaction["estabelecimento_id"],
                            transaction["parcela_atual"],
                            transaction["total_parcelas"],
                            transaction["pagina_origem"],
                        )
                        for index, transaction in enumerate(payload["transacoes"], start=1)
                    ],
                )
                cursor.execute(
                    """
                    INSERT INTO spend_label.estabelecimentos(id, nome_canonico)
                    SELECT estabelecimento_id, MIN(descricao)
                    FROM financeiro.transacoes_versao
                    WHERE versao_id = %s
                    GROUP BY estabelecimento_id
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (version_id,),
                )
                cursor.execute(
                    """
                    INSERT INTO spend_label.aliases_estabelecimento(
                        alias_hash, estabelecimento_id, descricao_normalizada,
                        origem, confirmado
                    )
                    SELECT
                        estabelecimento_id,
                        estabelecimento_id,
                        MIN(descricao_normalizada),
                        'importacao',
                        FALSE
                    FROM financeiro.transacoes_versao
                    WHERE versao_id = %s
                    GROUP BY estabelecimento_id
                    ON CONFLICT DO NOTHING
                    """,
                    (version_id,),
                )
        return ImportReceipt(version_id, False)

    def probe(self) -> ConnectionStatus:
        started = time.perf_counter()
        try:
            with self._connect(timeout=3) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            status, detail = "ok", "query_ok"
        except Exception:
            status, detail = "error", "unavailable"
        return ConnectionStatus(
            self.component, status, round((time.perf_counter() - started) * 1000, 2), detail
        )
