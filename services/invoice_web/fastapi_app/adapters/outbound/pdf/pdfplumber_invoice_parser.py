"""Parser geometrico de faturas Itau, sem registrar conteudo em logs."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pdfplumber


DATE_RE = re.compile(r"^(?P<day>\d{2})/(?P<month>\d{2})\s+")
DATE_TOKEN_RE = re.compile(r"^\d{2}/\d{2}$")
AMOUNT_RE = re.compile(
    r"(?P<before>-?)\s*(?:R\$\s*)?"
    r"(?P<amount>(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})\s*(?P<after>-?)$"
)
MONEY_TOKEN_RE = re.compile(
    r"^-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}-?$"
)
EMBEDDED_MONEY_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")
INSTALLMENT_RE = re.compile(r"(?<!\d)(?P<current>\d{1,2})/(?P<total>\d{1,2})(?!\d)")
INSTALLMENT_PREFIX_RE = re.compile(
    r"(?:\*[A-Z]|PARC(?:ELA)?\.?)\s*$", re.IGNORECASE
)
CATEGORY_PATTERNS = (
    ("alimentacao", (r"\bsupermercados?\b", r"\bmercado\b", r"\bpadaria\b", r"\bifood\b")),
    ("restaurante", (r"\brestaurante\b", r"\bcafe\b", r"\bbacio\b")),
    ("transporte", (r"\buber\b", r"\b99app\b", r"\bposto\b", r"\bpedagio\b")),
    ("saude", (r"\bfarmacia\b", r"\bdrogaria\b", r"\bclinica\b", r"\bhospital\b")),
    ("assinaturas", (r"\bnetflix\b", r"\bspotify\b", r"\byoutube\b", r"\bprime video\b")),
    ("educacao", (r"\bescola\b", r"\bfaculdade\b", r"\bcurso\b", r"\blivraria\b")),
)
PDF_CATEGORIES = {
    "alimentacao": "alimentacao",
    "educacao": "educacao",
    "eletronicos": "eletronicos",
    "entretenimento": "entretenimento",
    "lazer": "lazer",
    "moradia": "moradia",
    "outros": "outros",
    "restaurante": "restaurante",
    "saude": "saude",
    "servicos": "servicos",
    "transporte": "transporte",
    "viagem": "viagem",
    "vestuario": "vestuario",
}


@dataclass(frozen=True)
class TableLayout:
    left: float
    right: float
    description_x: float
    value_x: float
    header_top: float
    bottom: float
    title: str


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def _normalized_description(value: str) -> str:
    return _ascii(" ".join(value.split())).upper()[:180]


def _category(description: str) -> str:
    searchable = _normalized_description(description).lower()
    for category, patterns in CATEGORY_PATTERNS:
        if any(re.search(pattern, searchable) for pattern in patterns):
            return category
    return "outros"


def _merchant_id(description: str, key: bytes) -> str:
    stable_description = _ascii(" ".join(description.split()))[:180]
    digest = hmac.new(
        key, stable_description.encode(), hashlib.sha256
    ).hexdigest()
    return f"est_{digest[:12]}"


def _merchant_description(description: str, installment: re.Match | None) -> str:
    """Remove somente a notacao de parcela, preservando o nome reconhecivel."""
    if installment is None:
        return description[:180]
    before = INSTALLMENT_PREFIX_RE.sub("", description[:installment.start()]).strip()
    after = description[installment.end():].strip(" -|;")
    cleaned = " ".join(part for part in (before, after) if part).strip(" -|;")
    return (cleaned or description)[:180]


def _strip_location_suffix(description: str, location: str | None) -> str:
    if not location:
        return description
    searchable = _ascii(description)
    location_tokens = [token for token in _ascii(location).split() if len(token) >= 3]
    for token in location_tokens:
        for size in range(len(token), 2, -1):
            if searchable.endswith(token[:size]):
                return description[:-size].rstrip(" -|;") or description
    return description


def _decimal_from_text(value: str) -> Decimal:
    normalized = value.strip()
    negative = normalized.startswith("-") or normalized.endswith("-")
    number = Decimal(normalized.strip("-").replace(".", "").replace(",", "."))
    return -number if negative else number


def parse_transaction_line(line: str, page_number: int, reference_date: date, key: bytes):
    normalized = " ".join(line.split()).strip()
    date_match = DATE_RE.match(normalized)
    if not date_match:
        return None
    remainder = normalized[date_match.end():]
    amount_match = AMOUNT_RE.search(remainder)
    if not amount_match:
        return None
    description = remainder[:amount_match.start()].strip(" -|;")
    if not description:
        return None
    day = int(date_match.group("day"))
    month = int(date_match.group("month"))
    year = reference_date.year - (1 if month > reference_date.month else 0)
    try:
        transaction_date = date(year, month, day)
    except ValueError:
        return None
    amount = _decimal_from_text(
        f"{amount_match.group('before')}{amount_match.group('amount')}"
        f"{amount_match.group('after')}"
    )
    installment = INSTALLMENT_RE.search(description)
    current = total = None
    if installment:
        candidate_current = int(installment.group("current"))
        candidate_total = int(installment.group("total"))
        if 1 <= candidate_current <= candidate_total <= 99:
            current, total = candidate_current, candidate_total
    merchant_description = _merchant_description(description, installment)
    return {
        "data_iso": transaction_date.isoformat(),
        "valor": format(amount, ".2f"),
        "tipo": "credito" if amount < 0 else "compra",
        "categoria": _category(merchant_description),
        "descricao": merchant_description,
        "descricao_normalizada": _normalized_description(merchant_description),
        "localidade": None,
        "estabelecimento_id": _merchant_id(merchant_description, key),
        "parcela_atual": current,
        "total_parcelas": total,
        "pagina_origem": page_number,
    }


def _word_bands(words: list[dict[str, Any]], tolerance: float = 2.0) -> list[list[dict[str, Any]]]:
    bands: list[list[dict[str, Any]]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        band = next(
            (
                candidate
                for candidate in reversed(bands)
                if abs(candidate[0]["top"] - word["top"]) <= tolerance
            ),
            None,
        )
        if band is None:
            bands.append([word])
        else:
            band.append(word)
    return bands


def _scoped_words(band: list[dict[str, Any]], left: float, right: float) -> list[dict[str, Any]]:
    return sorted(
        [word for word in band if word["x0"] >= left - 2 and word["x1"] <= right + 2],
        key=lambda item: item["x0"],
    )


def _band_text(band: list[dict[str, Any]], left: float, right: float) -> str:
    return " ".join(word["text"] for word in _scoped_words(band, left, right))


def _discover_tables(words: list[dict[str, Any]], page_height: float) -> tuple[list[list[dict[str, Any]]], list[TableLayout]]:
    bands = _word_bands(words)
    candidates: list[dict[str, Any]] = []
    for band in bands:
        for establishment in (
            word for word in band if _ascii(word["text"]) == "estabelecimento"
        ):
            dates = [
                word
                for word in band
                if _ascii(word["text"]) == "data" and word["x0"] < establishment["x0"]
            ]
            if not dates:
                continue
            date_word = max(dates, key=lambda item: item["x0"])
            values = [
                word
                for word in band
                if word["x0"] > establishment["x1"]
                and _ascii(word["text"]) in {"valor", "r$"}
            ]
            if not values:
                continue
            value_word = max(values, key=lambda item: item["x0"])
            trailing = [
                word
                for word in band
                if value_word["x0"] <= word["x0"] <= value_word["x0"] + 65
            ]
            right = max(word["x1"] for word in trailing)
            header_top = float(establishment["top"])
            title = ""
            for title_band in reversed(bands):
                title_top = float(title_band[0]["top"])
                if not header_top - 35 <= title_top <= header_top - 5:
                    continue
                candidate_title = _band_text(
                    title_band, float(date_word["x0"]), right
                )
                normalized_title = _ascii(candidate_title)
                if "lancamentos" in normalized_title or "compras parceladas" in normalized_title:
                    title = candidate_title
                    break
            candidates.append(
                {
                    "left": float(date_word["x0"]),
                    "right": right,
                    "description_x": float(establishment["x0"]),
                    "value_x": float(value_word["x0"]),
                    "header_top": header_top,
                    "title": title,
                }
            )

    tables: list[TableLayout] = []
    for candidate in candidates:
        normalized_title = _ascii(candidate["title"])
        if not (
            "lancamentos" in normalized_title
            and "proximas faturas" not in normalized_title
        ):
            continue
        later_headers = [
            other["header_top"]
            for other in candidates
            if other["header_top"] > candidate["header_top"]
            and abs(other["left"] - candidate["left"]) <= 35
        ]
        bottom = min(later_headers) - 2 if later_headers else page_height - 45
        tables.append(TableLayout(bottom=bottom, **candidate))
    return bands, sorted(tables, key=lambda table: (table.left, table.header_top))


def _metadata_after_row(bands: list[list[dict[str, Any]]], table: TableLayout, row_top: float, next_row_top: float) -> tuple[str | None, str | None]:
    for band in bands:
        top = float(band[0]["top"])
        if not row_top + 3 <= top < min(next_row_top, row_top + 14):
            continue
        words = [
            word
            for word in _scoped_words(band, table.description_x, table.value_x - 4)
            if word["text"].strip()
        ]
        if not words:
            continue
        category = PDF_CATEGORIES.get(_ascii(words[0]["text"]))
        if category:
            location = " ".join(word["text"] for word in words[1:]).strip() or None
            return category, location
    return None, None


def _extract_table_transactions(page: Any, page_number: int, reference_date: date, key: bytes) -> tuple[list[dict[str, Any]], int]:
    words = page.extract_words(x_tolerance=1, y_tolerance=2, keep_blank_chars=False)
    bands, tables = _discover_tables(words, float(page.height))
    transactions: list[dict[str, Any]] = []
    for table in tables:
        row_bands: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
        for band in bands:
            top = float(band[0]["top"])
            if not table.header_top + 3 < top < table.bottom:
                continue
            scoped = _scoped_words(band, table.left, table.right)
            date_word = next(
                (
                    word
                    for word in scoped
                    if DATE_TOKEN_RE.match(word["text"])
                    and abs(float(word["x0"]) - table.left) <= 4
                ),
                None,
            )
            if date_word is not None:
                row_bands.append((scoped, date_word))

        for index, (row_words, date_word) in enumerate(row_bands):
            amounts = [
                word
                for word in row_words
                if MONEY_TOKEN_RE.match(word["text"])
                and float(word["x0"]) >= table.value_x - 28
            ]
            if not amounts:
                continue
            amount_word = max(amounts, key=lambda item: item["x0"])
            description_words = [
                word
                for word in row_words
                if float(word["x0"]) >= table.description_x - 2
                and float(word["x1"]) < float(amount_word["x0"]) - 1
            ]
            description = " ".join(word["text"] for word in description_words).strip()
            if not description:
                continue
            transaction = parse_transaction_line(
                f"{date_word['text']} {description} {amount_word['text']}",
                page_number,
                reference_date,
                key,
            )
            if transaction is None:
                continue
            next_top = (
                float(row_bands[index + 1][0][0]["top"])
                if index + 1 < len(row_bands)
                else table.bottom
            )
            category, location = _metadata_after_row(
                bands, table, float(date_word["top"]), next_top
            )
            cleaned = _strip_location_suffix(transaction["descricao"], location)
            transaction["descricao"] = cleaned
            transaction["descricao_normalizada"] = _normalized_description(cleaned)
            transaction["categoria"] = category or _category(cleaned)
            transaction["localidade"] = location
            transaction["estabelecimento_id"] = _merchant_id(cleaned, key)
            transactions.append(transaction)

        if "internacionais" in _ascii(table.title):
            for band in bands:
                top = float(band[0]["top"])
                if not table.header_top + 3 < top < table.bottom:
                    continue
                scoped = _scoped_words(band, table.left, table.right)
                text = " ".join(word["text"] for word in scoped)
                if "repasse de iof" not in _ascii(text):
                    continue
                amounts = [word for word in scoped if MONEY_TOKEN_RE.match(word["text"])]
                if not amounts:
                    continue
                amount = _decimal_from_text(max(amounts, key=lambda item: item["x0"])["text"])
                description = "Repasse de IOF"
                transactions.append(
                    {
                        "data_iso": None,
                        "valor": format(amount, ".2f"),
                        "tipo": "compra",
                        "categoria": "encargos",
                        "descricao": description,
                        "descricao_normalizada": _normalized_description(description),
                        "localidade": None,
                        "estabelecimento_id": _merchant_id(description, key),
                        "parcela_atual": None,
                        "total_parcelas": None,
                        "pagina_origem": page_number,
                    }
                )
    return transactions, len(tables)


def _current_total(page: Any) -> Decimal | None:
    words = page.extract_words(x_tolerance=1, y_tolerance=2, keep_blank_chars=False)
    for band in _word_bands(words):
        text = " ".join(word["text"] for word in sorted(band, key=lambda item: item["x0"]))
        if "total dos lancamentos atuais" not in _ascii(text):
            continue
        amounts = [word for word in band if MONEY_TOKEN_RE.match(word["text"])]
        if amounts:
            return _decimal_from_text(max(amounts, key=lambda item: item["x0"])["text"])
    return None


class PdfPlumberInvoiceParser:
    def __init__(self, private_root: Path):
        self.private_root = private_root.resolve()
        self.key_path = self.private_root / "secrets" / "fatura.hmac"

    def _resolve(self, reference: str) -> Path:
        path = (self.private_root / reference).resolve()
        path.relative_to(self.private_root)
        return path

    def _key(self) -> bytes:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            if len(key) != 32:
                raise ValueError("invalid local key")
            return key
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        with self.key_path.open("xb") as key_file:
            key_file.write(key)
        return key

    def parse(self, document_reference: str, reference_date: date, document_id: str, version_number: int, password: str | None) -> dict:
        key = self._key()
        transactions: list[dict[str, Any]] = []
        expected_total = None
        table_count = 0
        pdf_path = self._resolve(document_reference)
        with pdfplumber.open(str(pdf_path), password=password) as pdf:
            if len(pdf.pages) > 100:
                raise ValueError("too many pages")
            pages_processed = len(pdf.pages)
            for page_number, page in enumerate(pdf.pages, start=1):
                page_transactions, page_tables = _extract_table_transactions(
                    page, page_number, reference_date, key
                )
                transactions.extend(page_transactions)
                table_count += page_tables
                expected_total = expected_total or _current_total(page)

        warnings: list[str] = []
        if table_count == 0:
            warnings.append("transaction_tables_not_found")
        if not transactions:
            raise ValueError("no transactions")
        if any(Decimal(item["valor"]) == 0 for item in transactions):
            warnings.append("zero_value_transaction")
        if any(EMBEDDED_MONEY_RE.search(item["descricao"]) for item in transactions):
            warnings.append("embedded_amount_in_description")
        extracted_total = sum(Decimal(item["valor"]) for item in transactions)
        difference = None if expected_total is None else extracted_total - expected_total
        if expected_total is None:
            warnings.append("current_total_not_found")
        elif difference != 0:
            warnings.append("current_total_mismatch")
        quality_status = "ready" if not warnings else "needs_review"
        canonical = json.dumps(transactions, sort_keys=True, separators=(",", ":"))
        return {
            "schema": "fatura-itau/v3",
            "documento_id": document_id,
            "numero_versao": version_number,
            "gerado_em": datetime.now(timezone.utc).isoformat(),
            "data_referencia": reference_date.isoformat(),
            "conteudo_hash": hashlib.sha256(canonical.encode()).hexdigest(),
            "qualidade": {
                "status": quality_status,
                "avisos": warnings,
                "total_extraido": format(extracted_total, ".2f"),
                "total_lancamentos_pdf": (
                    format(expected_total, ".2f") if expected_total is not None else None
                ),
                "diferenca": format(difference, ".2f") if difference is not None else None,
            },
            "resumo": {
                "paginas_processadas": pages_processed,
                "tabelas_processadas": table_count,
                "transacoes_extraidas": len(transactions),
            },
            "transacoes": transactions,
        }
