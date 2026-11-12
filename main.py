from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.stock_processor import build_vtex_stock_file, save_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera o ajuste de estoque VTEX a partir do GIX.")
    parser.add_argument("gix_csv", type=Path, help="Relatório CSV do GIX")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Diretório dos arquivos CSV e XLS (padrão: diretório atual)",
    )
    arguments = parser.parse_args()

    frame, diagnostics = build_vtex_stock_file(arguments.gix_csv)
    csv_path, xls_path = save_outputs(frame, arguments.output_dir)
    print(f"CSV gerado: {csv_path}")
    print(f"XLS gerado: {xls_path}")
    print(f"Linhas exportadas: {len(frame)}")
    for diagnostic in diagnostics:
        print(f"Aviso: {diagnostic['message']}")
        if diagnostic["records"]:
            print(json.dumps(diagnostic["records"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
