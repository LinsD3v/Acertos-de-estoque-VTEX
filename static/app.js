const form = document.querySelector("#process-form");
const submitButton = document.querySelector("#submit-button");
const statusMessage = document.querySelector("#status");
const resultPanel = document.querySelector("#result");
const recordCount = document.querySelector("#record-count");
const previewHead = document.querySelector("#preview-head");
const previewBody = document.querySelector("#preview-body");
const previewEmpty = document.querySelector("#preview-empty");
const diagnosticsPanel = document.querySelector("#diagnostics-panel");
const diagnosticsList = document.querySelector("#diagnostics");
const csvButton = document.querySelector("#download-csv");
const xlsButton = document.querySelector("#download-xls");

let outputFiles = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  outputFiles = null;
  resultPanel.hidden = true;
  statusMessage.textContent = "Processando os arquivos...";
  submitButton.disabled = true;

  try {
    const response = await fetch("/api/process", {
      method: "POST",
      body: new FormData(form),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Não foi possível processar os arquivos.");
    }

    outputFiles = result.files;
    recordCount.textContent = `${result.record_count} linha(s) processada(s)`;
    renderPreview(result.preview);
    renderDiagnostics(result.diagnostics);
    resultPanel.hidden = false;
    statusMessage.textContent = "Processamento concluído.";
  } catch (error) {
    statusMessage.textContent = error.message || "Falha de comunicação com o servidor.";
  } finally {
    submitButton.disabled = false;
  }
});

csvButton.addEventListener("click", () => downloadFile("csv"));
xlsButton.addEventListener("click", () => downloadFile("xls"));

function renderPreview(rows) {
  previewHead.replaceChildren();
  previewBody.replaceChildren();
  previewEmpty.hidden = rows.length > 0;
  if (rows.length === 0) return;

  const headerRow = document.createElement("tr");
  for (const column of Object.keys(rows[0])) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = column;
    headerRow.append(cell);
  }
  previewHead.append(headerRow);
  for (const row of rows) {
    const tableRow = document.createElement("tr");
    for (const value of Object.values(row)) {
      const cell = document.createElement("td");
      cell.textContent = value ?? "";
      tableRow.append(cell);
    }
    previewBody.append(tableRow);
  }
}

function renderDiagnostics(diagnostics) {
  diagnosticsList.replaceChildren();
  diagnosticsPanel.hidden = diagnostics.length === 0;
  for (const diagnostic of diagnostics) {
    const item = document.createElement("li");
    item.textContent = diagnostic.message;
    if (diagnostic.records?.length) {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `Ver ${diagnostic.records.length} registro(s)`;
      const records = document.createElement("pre");
      records.textContent = JSON.stringify(diagnostic.records, null, 2);
      details.append(summary, records);
      item.append(details);
    }
    diagnosticsList.append(item);
  }
}

function downloadFile(format) {
  if (!outputFiles || !outputFiles[format]) return;

  const file = outputFiles[format];
  const binary = atob(file.base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const blob = new Blob([bytes], { type: file.content_type });
  const link = document.createElement("a");
  const downloadUrl = URL.createObjectURL(blob);
  link.href = downloadUrl;
  link.download = file.filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
}
