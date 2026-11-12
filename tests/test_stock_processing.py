from __future__ import annotations

import csv
import io
import tempfile
import unittest
from pathlib import Path

from backend.product_map import DEFAULT_MAPPING_PATH, ProductMapError, load_product_map
from backend.stock_processor import COLUMNS, build_vtex_stock_file, save_outputs


MAP_HEADER = "gix;SkuId;EAN-13;Descrição\n"
TEST_MAP = (
    MAP_HEADER
    + "0001;00123;7891234567890;Produto com EAN\n"
    + "0002;00456;0;Produto sem EAN\n"
)


class ProductMapTests(unittest.TestCase):
    def test_default_map_preserves_identifiers_and_reports_incomplete_rows(self) -> None:
        product_map = load_product_map(DEFAULT_MAPPING_PATH)

        self.assertEqual(product_map.products["0020197"].sku_id, "119917")
        self.assertEqual(product_map.products["0020197"].ean, "7891019177189")
        self.assertIn("invalid_mapping_rows", [item["code"] for item in product_map.diagnostics])
        invalid = next(
            item for item in product_map.diagnostics if item["code"] == "invalid_mapping_rows"
        )
        self.assertEqual(len(invalid["records"]), 94)

    def test_identical_gix_rows_are_deduplicated_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mapa.csv"
            path.write_text(TEST_MAP + "0001;00123;7891234567890;Produto com EAN\n", encoding="utf-8-sig")

            product_map = load_product_map(path)

        duplicates = next(
            item for item in product_map.diagnostics if item["code"] == "duplicate_mapping_rows"
        )
        self.assertEqual(duplicates["records"], [{"gix": "0001", "rows": [2, 4]}])
        self.assertEqual(len(product_map.products), 2)

    def test_conflicting_gix_rows_stop_with_row_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mapa.csv"
            path.write_text(
                TEST_MAP + "0001;99999;7891234567890;Outro SKU\n",
                encoding="utf-8-sig",
            )

            with self.assertRaisesRegex(ProductMapError, r"GIX '0001'.*linha 2.*linha 4.*99999"):
                load_product_map(path)

    def test_invalid_map_header_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mapa.csv"
            path.write_text("GIX;SkuId;EAN;Descrição\n0001;1;0;Produto\n", encoding="utf-8-sig")

            with self.assertRaisesRegex(ProductMapError, "Cabeçalho inválido"):
                load_product_map(path)

    def test_ean_associated_with_multiple_skus_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mapa.csv"
            path.write_text(
                MAP_HEADER
                + "0001;001;7891234567890;Produto A\n"
                + "0002;002;7891234567890;Produto B\n",
                encoding="utf-8-sig",
            )

            with self.assertRaisesRegex(ProductMapError, r"EAN-13.*linha 2.*linha 3"):
                load_product_map(path)


class StockProcessorTests(unittest.TestCase):
    def write_inputs(self, temp_dir: str) -> tuple[Path, Path]:
        root = Path(temp_dir)
        map_path = root / "mapa.csv"
        map_path.write_text(TEST_MAP, encoding="utf-8-sig")
        gix_path = root / "gix.csv"
        gix_path.write_text(
            "CÓDIGO;ESTOQUEATUAL\n"
            "0001;7,75\n"
            "0002;1.234,75\n"
            "0001;\n"
            "0002;estoque-inválido\n"
            "9999;4\n",
            encoding="utf-8-sig",
        )
        return gix_path, map_path

    def test_processes_ean_zero_invalid_quantities_and_unmatched_gix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gix_path, map_path = self.write_inputs(temp_dir)
            frame, diagnostics = build_vtex_stock_file(gix_path, map_path)

        self.assertEqual(list(frame.columns), COLUMNS)
        self.assertEqual(frame["SkuId"].tolist(), ["00123", "00123", "00456", "00456"])
        self.assertEqual(frame["TotalQuantity"].tolist(), [7, 0, 1234, 0])
        self.assertEqual(frame["AvailableQuantity"].tolist(), [7, 0, 1234, 0])
        self.assertEqual(frame["RefId"].tolist(), ["7891234567890", "7891234567890", 0, 0])
        codes = {item["code"] for item in diagnostics}
        self.assertIn("unmatched_gix", codes)
        self.assertIn("invalid_quantities", codes)
        self.assertIn("duplicate_sku_rows", codes)

    def test_output_contract_csv_and_legacy_xls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gix_path, map_path = self.write_inputs(temp_dir)
            frame, _ = build_vtex_stock_file(gix_path, map_path)
            csv_path, xls_path = save_outputs(frame, Path(temp_dir) / "output")

            raw_csv = csv_path.read_bytes()
            self.assertTrue(raw_csv.startswith(b"\xef\xbb\xbf"))
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source, delimiter=",")
                rows = list(reader)
            self.assertEqual(reader.fieldnames, COLUMNS)
            self.assertEqual(rows[0]["SkuId"], "00123")
            self.assertEqual(rows[2]["RefId"], "0")
            self.assertEqual(rows[0]["LockIds"], "")
            self.assertTrue(xls_path.read_bytes().startswith(bytes.fromhex("D0CF11E0A1B11AE1")))

    def test_malformed_gix_row_is_reported_as_processing_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, map_path = self.write_inputs(temp_dir)
            gix_path = Path(temp_dir) / "bad.csv"
            gix_path.write_text("CÓDIGO;ESTOQUEATUAL\n0001\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Linha 2"):
                build_vtex_stock_file(gix_path, map_path)


if __name__ == "__main__":
    unittest.main()
