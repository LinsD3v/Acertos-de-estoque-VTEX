# Acerto de estoque GIX → VTEX

Aplicação web única para gerar arquivos de importação de estoque da VTEX. O processamento associa os códigos GIX ao SKU e ao EAN pelo mapa consolidado `data/maps/mapa.csv`; não há seleção de fornecedor nem envio de mapa pela interface.

## Arquitetura

- `backend/product_map.py`: carrega, valida e diagnostica o mapa GIX/SKU/EAN.
- `backend/stock_processor.py`: interpreta o relatório GIX, aplica as regras de estoque e gera CSV/XLS.
- `backend/app.py`: autenticação, endpoints, prévia e downloads.
- `templates/` e `static/`: interface da aplicação.
- `main.py`: opção CLI, com o caminho do relatório GIX informado pelo operador.

As requisições gravam arquivos somente em diretórios temporários próprios; o mapa é somente leitura e faz parte do deploy.

## Regras integradas

- A associação é sempre `GIX → mapa → SkuId/EAN-13`; o identificador é texto, inclusive quando contém zeros à esquerda.
- `EAN-13` válido é usado em `RefId`; `"0"` gera o valor `0`, convenção de ausência de EAN já usada no arquivo BASF.
- Estoque ausente ou inválido permanece compatível com os projetos originais e vira `0`, com diagnóstico.
- `ReservedQuantity=0`, `AvailableQuantity=TotalQuantity`, `WarehouseId=1_1`, `WarehouseName=Estoque principal`, `IsActive=True`, `UnlimitedQuantity=False`, `LockIds` vazio e `DispatchedReservations=0`.
- A saída usa as colunas, separador vírgula e BOM UTF-8 do fluxo web BASF, além do XLS legado, aba `Estoque VTEX`.
- Linhas GIX sem correspondência são omitidas e informadas. Códigos e SKUs repetidos não têm quantidades agregadas; são preservados e diagnosticados.
- Linhas do mapa sem SKU ou com EAN inválido são ignoradas e listadas no diagnóstico. Duplicatas GIX idênticas são deduplicadas e informadas; dados conflitantes para um mesmo GIX ou um EAN válido associado a SKUs diferentes interrompem a operação (validação do fluxo AKZO).

O mapa fornecido contém atualmente 94 linhas sem `SkuId`; elas são apresentadas nos diagnósticos e não geram saída até que o mapa seja corrigido.

## Comparação com os projetos anteriores

- BASF lia CSV GIX e cruzava `CODIGO`/estoque com um mapa GIX→SKU; a leitura pandas não declarava `dtype=str`, podendo remover zeros à esquerda. O contrato web era CSV com vírgula e BOM, XLS legado e `LockIds`.
- AKZO lia CSV GIX e associava pelo EAN, gerava seu mapa lendo todas as planilhas do XLS VTEX, validava EAN duplicado e exportava CSV com `;` e `LockId`. `EAN="0"` não passava pela validação de EAN-13 e era omitido.
- No fluxo integrado, o GIX é preservado como texto e a associação usa somente o mapa pronto. A geração do mapa AKZO/XLS deixou de ser executada; o GIX de entrada continua CSV, então leitura multi-planilha não se aplica.
- Foi preservado o contrato de saída da aplicação BASF (`LockIds`, vírgula, BOM e XLS), usando o EAN do mapa como `RefId` e `0` como ausência. Ambos os processadores anteriores definiam reserva como zero e disponível igual ao total.

Na validação dos arquivos de referência, o processador integrado produziu 401 linhas para o GIX AKZO e 399 para o GIX BASF; no exemplo BASF antigo eram 302. O relatório BASF teve 345 códigos sem associação no mapa consolidado. Comparando os 396 códigos do mapa BASF antigo com os registros correspondentes no formato GIX do mapa novo, 130 `SkuId` diferem. As associações em produção seguem o mapa consolidado; os códigos sem associação e as diferenças de SKU precisam de validação do responsável pelos dados antes de considerar esses relatórios históricos integralmente cobertos.

## Execução local

Instale as dependências e configure a autenticação:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edite `.env` com `APP_PASSWORD` e `SECRET_KEY`. Execute a aplicação Flask ou o fluxo CLI:

```powershell
flask --app app run
python main.py caminho\para\relatorio.csv --output-dir caminho\para\saida
```

O endpoint web aceita `POST /api/process` com o arquivo `gix_file`. `GET /api/health`, a página e os assets também exigem autenticação, exceto a tela de login e seu CSS. O processamento responde com prévia, diagnósticos e arquivos CSV/XLS codificados em Base64.

## Testes

```powershell
python -m unittest discover -s tests -v
```

O GIX de entrada é CSV; leitura de arquivos VTEX Excel com múltiplas planilhas pertence somente à geração histórica do mapa AKZO, que foi substituída pelo mapa consolidado pronto. Não é uma entrada do fluxo unificado.
