"""Popula os volumes isolados usados na apresentacao do sistema."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi_app.adapters.outbound.filesystem import LocalDocumentStorage
from fastapi_app.adapters.outbound.persistence import (
    PostgresVersionPublisher,
    SQLiteInvoiceRepository,
)
from fastapi_app.infrastructure.config import PostgresSettings


INVOICE_ID = "7f0cb04d-2914-4cb8-a05b-580608fced3a"
REFERENCE_DATE = "2026-08-01"
CONTENT_HASH = "d3a4f7c99a11e546bb3863d4a59c884ee17905fc8ef58cdbe3c92fd690f15297"

PURCHASES = [
    ("2026-08-02", "Supermercado Aurora", "486.72", "alimentacao", "Sao Paulo - SP", None, None),
    ("2026-08-03", "Posto Avenida", "280.00", "transporte", "Sao Paulo - SP", None, None),
    ("2026-08-04", "Netflix", "55.90", "assinaturas", None, None, None),
    ("2026-08-05", "Farmacia Bem Estar", "89.35", "saude", "Sao Paulo - SP", None, None),
    ("2026-08-07", "Restaurante Jardim", "134.60", "restaurante", "Sao Paulo - SP", None, None),
    ("2026-08-09", "Cinema Central", "48.00", "lazer", "Sao Paulo - SP", None, None),
    ("2026-08-11", "Livraria Horizonte", "76.40", "educacao", "Sao Paulo - SP", None, None),
    ("2026-08-13", "Loja Estilo", "219.90", "vestuario", "Sao Paulo - SP", None, None),
    ("2026-08-15", "Energia Eletrica", "178.44", "moradia", None, None, None),
    ("2026-08-16", "Internet Fibra", "119.90", "servicos", None, None, None),
    ("2026-08-18", "Passagens Brasil", "620.00", "viagem", "Rio de Janeiro - RJ", 2, 6),
    ("2026-08-21", "Notebook Store", "329.90", "eletronicos", "Sao Paulo - SP", 5, 10),
    ("2026-08-24", "Cafe da Praca", "32.50", "alimentacao", "Sao Paulo - SP", None, None),
]


def merchant_id(description: str) -> str:
    return hashlib.md5(description.upper().encode("utf-8"), usedforsecurity=False).hexdigest()


def transaction(item: tuple, page: int) -> dict:
    date, description, amount, category, location, installment, installments = item
    return {
        "data_iso": date,
        "valor": amount,
        "tipo": "compra",
        "categoria": category,
        "descricao": description,
        "descricao_normalizada": description.upper(),
        "localidade": location,
        "estabelecimento_id": merchant_id(description),
        "parcela_atual": installment,
        "total_parcelas": installments,
        "pagina_origem": page,
    }


def build_payload() -> dict:
    transactions = [
        transaction(item, 1 if index < 8 else 2)
        for index, item in enumerate(PURCHASES, start=1)
    ]
    total = sum((Decimal(item["valor"]) for item in transactions), Decimal("0"))
    generated_at = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc).isoformat()
    return {
        "documento_id": INVOICE_ID,
        "nome": "Cartao principal - Agosto 2026",
        "numero_versao": 1,
        "conteudo_hash": CONTENT_HASH,
        "data_referencia": REFERENCE_DATE,
        "gerado_em": generated_at,
        "qualidade": {
            "status": "ready",
            "total_extraido": str(total),
            "total_lancamentos_pdf": str(total),
        },
        "resumo": {
            "transacoes_extraidas": len(transactions),
            "total_extraido": str(total),
        },
        "transacoes": transactions,
    }


def seed_sqlite(private_root: Path, payload: dict, postgres_version_id: int) -> None:
    repository = SQLiteInvoiceRepository(private_root / "invoice-registry.sqlite3")
    storage = LocalDocumentStorage(private_root)
    pdf_reference = f"uploads/{INVOICE_ID}/fatura.pdf"
    pdf_path = storage.resolve(pdf_reference)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4\n% Demo sem dados reais\n%%EOF\n")
    json_reference = storage.save_payload(INVOICE_ID, 1, payload)

    with repository.session() as connection:
        connection.execute("DELETE FROM invoices WHERE id = ?", (INVOICE_ID,))
    repository.create(
        INVOICE_ID,
        payload["nome"],
        "fatura-cartao-agosto-2026.pdf",
        pdf_reference,
        REFERENCE_DATE,
    )
    repository.finish_processing(
        INVOICE_ID,
        1,
        json_reference,
        CONTENT_HASH,
        len(payload["transacoes"]),
        "ready",
    )
    repository.mark_imported(INVOICE_ID, 1, postgres_version_id)


def seed_cash_flow(publisher: PostgresVersionPublisher) -> None:
    with publisher._connect() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM cash_flow.recorrencias_lancamento_manual")
        cursor.execute("DELETE FROM cash_flow.lancamentos_manuais")
        cursor.execute("DELETE FROM cash_flow.gastos_previstos_cartao")
        cursor.execute("DELETE FROM cash_flow.resumos_mensais")
        cursor.execute(
            """
            INSERT INTO cash_flow.resumos_mensais(
                mes_referencia, rendimento, guardado_base
            ) VALUES ('2026-08-01', 8500.00, 18000.00)
            """
        )
        cursor.execute(
            """
            INSERT INTO cash_flow.lancamentos_manuais(
                mes_referencia, descricao, valor, categoria_id,
                meio_pagamento, tipo_lancamento
            )
            SELECT '2026-08-01', item.description, item.amount, category.id,
                   item.payment_method, 'actual'
            FROM (
                VALUES
                    ('Aluguel', 1850.00::numeric, 'moradia', 'pix'),
                    ('Academia', 109.90::numeric, 'saude', 'debito')
            ) AS item(description, amount, category_slug, payment_method)
            JOIN spend_label.categorias AS category
              ON category.slug = item.category_slug
            """
        )
        cursor.execute(
            """
            INSERT INTO cash_flow.gastos_previstos_cartao(
                mes_referencia, descricao, valor, categoria_id
            )
            SELECT '2026-09-01', 'Viagem de ferias', 780.00, id
            FROM spend_label.categorias WHERE slug = 'viagem'
            """
        )


def main() -> None:
    if os.environ.get("DEMO_SEED") != "1":
        raise RuntimeError("O seed so pode ser executado com DEMO_SEED=1.")
    payload = build_payload()
    publisher = PostgresVersionPublisher(PostgresSettings.from_environment())
    receipt = publisher.publish(payload)
    seed_cash_flow(publisher)
    seed_sqlite(Path(os.environ.get("PRIVATE_ROOT", "/app/private")), payload, receipt.version_id)
    print(
        f"Demo pronta: fatura {INVOICE_ID}, "
        f"{len(payload['transacoes'])} transacoes, versao PostgreSQL {receipt.version_id}."
    )


if __name__ == "__main__":
    main()
