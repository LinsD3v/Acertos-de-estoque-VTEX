from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAPPING_PATH = Path(__file__).resolve().parents[1] / "data" / "maps" / "mapa.csv"
MAP_COLUMNS = ("gix", "SkuId", "EAN-13", "Descrição")
EAN_PATTERN = re.compile(r"\d{13}\Z")


class ProductMapError(ValueError):
    """Erro de estrutura, conteúdo ou conflito no mapa unificado."""


@dataclass(frozen=True)
class Product:
    gix: str
    sku_id: str
    ean: str
    description: str


@dataclass(frozen=True)
class ProductMap:
    products: dict[str, Product]
    invalid_gix: frozenset[str]
    diagnostics: list[dict[str, object]]


def load_product_map(path: Path = DEFAULT_MAPPING_PATH) -> ProductMap:
    """Carrega o mapa GIX→SKU/EAN e informa duplicatas e linhas incompletas."""
    diagnostics: list[dict[str, object]] = []
    records_by_gix: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    invalid_rows: list[dict[str, object]] = []

    try:
        source = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ProductMapError(f"Não foi possível abrir o mapa de produtos: {exc}") from exc

    with source:
        reader = csv.reader(source, delimiter=";", strict=True)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ProductMapError("O mapa de produtos está vazio.") from exc
        except csv.Error as exc:
            raise ProductMapError(f"CSV inválido no cabeçalho do mapa: {exc}") from exc

        if tuple(header) != MAP_COLUMNS:
            raise ProductMapError(
                "Cabeçalho inválido no mapa de produtos. Esperado: "
                + ";".join(MAP_COLUMNS)
                + f". Encontrado: {';'.join(header)}"
            )

        try:
            for row_number, row in enumerate(reader, start=2):
                if not row:
                    invalid_rows.append({"row": row_number, "gix": "", "reason": "linha vazia"})
                    continue
                if len(row) != len(MAP_COLUMNS):
                    invalid_rows.append(
                        {
                            "row": row_number,
                            "gix": row[0].strip() if row else "",
                            "reason": f"esperados 4 campos, encontrados {len(row)}",
                        }
                    )
                    continue

                gix = row[0].strip()
                if not gix:
                    invalid_rows.append({"row": row_number, "gix": "", "reason": "GIX vazio"})
                    continue
                records_by_gix.setdefault(gix, []).append((row_number, tuple(row)))
        except csv.Error as exc:
            raise ProductMapError(f"CSV inválido no mapa de produtos: {exc}") from exc

    conflicts = []
    duplicates = []
    products: dict[str, Product] = {}
    invalid_gix: set[str] = set()
    products_by_ean: dict[str, list[tuple[int, str, str]]] = {}

    for gix, entries in records_by_gix.items():
        if len(entries) > 1:
            exact_rows: dict[tuple[str, ...], list[int]] = {}
            for row_number, row in entries:
                exact_rows.setdefault(row, []).append(row_number)
            if len(exact_rows) > 1:
                conflicts.append(
                    {
                        "gix": gix,
                        "records": [
                            {
                                "row": row_number,
                                "values": list(row),
                            }
                            for row_number, row in entries
                        ],
                    }
                )
                continue
            duplicates.append(
                {"gix": gix, "rows": [row_number for row_number, _ in entries]}
            )

        row_number, raw_row = entries[0]
        sku_id = raw_row[1].strip()
        ean = raw_row[2].strip()
        if not sku_id:
            invalid_gix.add(gix)
            invalid_rows.extend(
                {
                    "row": duplicate_row,
                    "gix": gix,
                    "reason": "SkuId vazio",
                }
                for duplicate_row, _ in entries
            )
            continue
        if ean != "0" and not EAN_PATTERN.fullmatch(ean):
            invalid_gix.add(gix)
            invalid_rows.extend(
                {
                    "row": duplicate_row,
                    "gix": gix,
                    "reason": f"EAN-13 inválido: {ean!r}",
                }
                for duplicate_row, _ in entries
            )
            continue

        products[gix] = Product(
            gix=gix,
            sku_id=sku_id,
            ean=ean,
            description=raw_row[3].strip(),
        )
        if ean != "0":
            products_by_ean.setdefault(ean, []).append((row_number, gix, sku_id))

    if conflicts:
        details = "; ".join(
            f"GIX {entry['gix']!r}: "
            + ", ".join(
                f"linha {item['row']}={item['values']!r}" for item in entry["records"]
            )
            for entry in conflicts
        )
        raise ProductMapError(
            "O mapa contém registros conflitantes para o mesmo GIX: " + details
        )

    conflicting_eans = {
        ean: entries
        for ean, entries in products_by_ean.items()
        if len({sku_id for _, _, sku_id in entries}) > 1
    }
    if conflicting_eans:
        details = "; ".join(
            f"EAN {ean!r}: "
            + ", ".join(
                f"linha {row_number} (GIX {gix!r}, SkuId {sku_id!r})"
                for row_number, gix, sku_id in entries
            )
            for ean, entries in conflicting_eans.items()
        )
        raise ProductMapError(
            "O mapa contém EAN-13 associado a mais de um SkuId: " + details
        )

    if invalid_rows:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "invalid_mapping_rows",
                "message": (
                    f"{len(invalid_rows)} linha(s) inválida(s) do mapa foram ignoradas."
                ),
                "records": invalid_rows,
            }
        )
    if duplicates:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "duplicate_mapping_rows",
                "message": (
                    f"{len(duplicates)} GIX com registros rigorosamente idênticos "
                    "foram deduplicados."
                ),
                "records": duplicates,
            }
        )
    if not products:
        raise ProductMapError("O mapa não contém nenhum registro utilizável.")

    return ProductMap(
        products=products,
        invalid_gix=frozenset(invalid_gix),
        diagnostics=diagnostics,
    )
