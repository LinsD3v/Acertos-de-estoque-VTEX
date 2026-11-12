from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from backend.product_map import DEFAULT_MAPPING_PATH, ProductMapError, load_product_map

COLUMNS = [
    "SkuId",
    "TotalQuantity",
    "ReservedQuantity",
    "AvailableQuantity",
    "WarehouseId",
    "WarehouseName",
    "RefId",
    "IsActive",
    "UnlimitedQuantity",
    "LockIds",
    "DispatchedReservations",
]


class StockProcessingError(ValueError):
    """Erro em arquivo GIX ou processamento de estoque."""


def _normalize_header(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def _read_gix_rows(path: Path) -> tuple[list[str], list[tuple[int, list[str]]]]:
    last_error: UnicodeError | None = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as source:
                reader = csv.reader(source, delimiter=";", strict=True)
                header = next(reader, None)
                if header is None:
                    raise StockProcessingError("O relatório GIX está vazio.")
                rows = [
                    (row_number, row)
                    for row_number, row in enumerate(reader, start=2)
                    if row
                ]
                return header, rows
        except UnicodeError as exc:
            last_error = exc
        except csv.Error as exc:
            raise StockProcessingError(f"CSV inválido no relatório GIX: {exc}") from exc
        except OSError as exc:
            raise StockProcessingError(f"Não foi possível ler o relatório GIX: {exc}") from exc

    raise StockProcessingError(
        f"Não foi possível decodificar o relatório GIX: {last_error}"
    )


def _find_column(header: list[str], names: tuple[str, ...], description: str) -> int:
    normalized = [_normalize_header(column) for column in header]
    for name in names:
        expected = _normalize_header(name)
        matches = [index for index, value in enumerate(normalized) if value == expected]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise StockProcessingError(
                f"Há mais de uma coluna compatível com {description}: {header!r}."
            )

    if description == "código GIX":
        candidates = [
            index
            for index, value in enumerate(normalized)
            if value.startswith("codigo") and "fabrica" not in value and "barra" not in value
        ]
    else:
        candidates = [
            index
            for index, value in enumerate(normalized)
            if "estoque" in value and ("atual" in value or value == "estoque")
        ]

    if len(candidates) == 1:
        return candidates[0]
    raise StockProcessingError(
        f"Não foi possível identificar a coluna de {description} no relatório GIX: "
        f"{header!r}."
    )


def _parse_quantity(value: str) -> tuple[int, str | None]:
    text = value.strip()
    if not text:
        return 0, "estoque vazio"

    localized = text.replace(".", "").replace(",", ".")
    try:
        number = Decimal(localized)
        if not number.is_finite():
            raise InvalidOperation
        return int(number), None
    except (InvalidOperation, ValueError, OverflowError):
        return 0, f"estoque inválido: {text!r}"


def _add_diagnostic(
    diagnostics: list[dict[str, object]],
    code: str,
    message: str,
    records: list[dict[str, object]],
) -> None:
    if records:
        diagnostics.append(
            {
                "severity": "warning",
                "code": code,
                "message": message,
                "records": records,
            }
        )


def build_vtex_stock_file(
    gix_path: Path,
    mapping_path: Path = DEFAULT_MAPPING_PATH,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    product_map = load_product_map(mapping_path)
    header, gix_rows = _read_gix_rows(gix_path)
    code_index = _find_column(header, ("CÓDIGO", "CODIGO GIX"), "código GIX")
    stock_index = _find_column(
        header,
        ("ESTOQUEATUAL", "ESTOQUE ATUAL", "ESTOQUE"),
        "estoque atual",
    )

    diagnostics = list(product_map.diagnostics)
    output_rows: list[dict[str, object]] = []
    unmatched: list[dict[str, object]] = []
    invalid_gix_rows: list[dict[str, object]] = []
    invalid_quantities: list[dict[str, object]] = []
    seen_gix: dict[str, list[int]] = defaultdict(list)

    for row_number, row in gix_rows:
        if len(row) != len(header):
            raise StockProcessingError(
                f"Linha {row_number} do relatório GIX tem {len(row)} campo(s); "
                f"eram esperados {len(header)}."
            )
        gix = row[code_index].strip()
        if not gix:
            invalid_gix_rows.append({"row": row_number, "reason": "código GIX vazio"})
            continue

        seen_gix[gix].append(row_number)
        product = product_map.products.get(gix)
        if product is None:
            unmatched.append(
                {
                    "row": row_number,
                    "gix": gix,
                    "reason": (
                        "registro do mapa sem SkuId ou com EAN inválido"
                        if gix in product_map.invalid_gix
                        else "GIX não encontrado no mapa"
                    ),
                }
            )
            continue

        quantity, quantity_issue = _parse_quantity(row[stock_index])
        if quantity_issue:
            invalid_quantities.append(
                {"row": row_number, "gix": gix, "reason": quantity_issue}
            )

        output_rows.append(
            {
                "SkuId": product.sku_id,
                "TotalQuantity": quantity,
                "ReservedQuantity": 0,
                "AvailableQuantity": quantity,
                "WarehouseId": "1_1",
                "WarehouseName": "Estoque principal",
                "RefId": 0 if product.ean == "0" else product.ean,
                "IsActive": True,
                "UnlimitedQuantity": False,
                "LockIds": "",
                "DispatchedReservations": 0,
            }
        )

    duplicate_gix_rows = [
        {"gix": gix, "rows": rows}
        for gix, rows in seen_gix.items()
        if len(rows) > 1
    ]
    duplicate_skus = [
        {"sku_id": sku, "count": count}
        for sku, count in Counter(str(row["SkuId"]) for row in output_rows).items()
        if count > 1
    ]
    _add_diagnostic(
        diagnostics,
        "unmatched_gix",
        f"{len(unmatched)} linha(s) GIX não tiveram associação utilizável e foram omitidas.",
        unmatched,
    )
    _add_diagnostic(
        diagnostics,
        "invalid_gix_rows",
        f"{len(invalid_gix_rows)} linha(s) sem código GIX foram omitidas.",
        invalid_gix_rows,
    )
    _add_diagnostic(
        diagnostics,
        "invalid_quantities",
        f"{len(invalid_quantities)} estoque(s) vazio(s) ou inválido(s) foram convertidos para 0.",
        invalid_quantities,
    )
    _add_diagnostic(
        diagnostics,
        "duplicate_gix_rows",
        f"{len(duplicate_gix_rows)} código(s) GIX aparecem mais de uma vez no relatório; "
        "as linhas foram preservadas.",
        duplicate_gix_rows,
    )
    _add_diagnostic(
        diagnostics,
        "duplicate_sku_rows",
        f"{len(duplicate_skus)} SKU(s) aparecem em mais de uma linha de saída; "
        "nenhuma quantidade foi agregada.",
        duplicate_skus,
    )

    output_rows.sort(
        key=lambda item: (
            0,
            int(str(item["SkuId"])),
        )
        if str(item["SkuId"]).isdigit()
        else (1, str(item["SkuId"]))
    )
    frame = pd.DataFrame(output_rows, columns=COLUMNS)
    return frame, diagnostics


def save_outputs(
    frame: pd.DataFrame,
    output_dir: Path,
) -> tuple[Path, Path]:
    import xlwt

    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / "estoque_vtex.csv"
    output_xls = output_dir / "estoque_vtex.xls"
    frame.to_csv(output_csv, index=False, sep=",", encoding="utf-8-sig")

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Estoque VTEX")
    header_style = xlwt.easyxf("font: bold on")
    for column_index, column in enumerate(frame.columns):
        sheet.write(0, column_index, column, header_style)
    for row_index, row in enumerate(frame.itertuples(index=False, name=None), start=1):
        for column_index, value in enumerate(row):
            if pd.isna(value):
                value = ""
            if frame.columns[column_index] in {"SkuId", "WarehouseId", "WarehouseName"}:
                sheet.write(row_index, column_index, str(value))
            else:
                sheet.write(row_index, column_index, value)
    workbook.save(str(output_xls))
    return output_csv, output_xls


__all__ = [
    "COLUMNS",
    "DEFAULT_MAPPING_PATH",
    "ProductMapError",
    "StockProcessingError",
    "build_vtex_stock_file",
    "save_outputs",
]
