const CODE128_PATTERNS = [
  "212222","222122","222221","121223","121322","131222","122213","122312","132212","221213",
  "221312","231212","112232","122132","122231","113222","123122","123221","223211","221132",
  "221231","213212","223112","312131","311222","321122","321221","312212","322112","322211",
  "212123","212321","232121","111323","131123","131321","112313","132113","132311","211313",
  "231113","231311","112133","112331","132131","113123","113321","133121","313121","211331",
  "231131","213113","213311","213131","311123","311321","331121","312113","312311","332111",
  "314111","221411","431111","111224","111422","121124","121421","141122","141221","112214",
  "112412","122114","122411","142112","142211","241211","221114","413111","241112","134111",
  "111242","121142","121241","114212","124112","124211","411212","421112","421211","212141",
  "214121","412121","111143","111341","131141","114113","114311","411113","411311","113141",
  "114131","311141","411131","211412","211214","211232","2331112"
];

const ACTIONS = [
  { title: "Plus Bestand", code: "ADD", hint: "Zugang lokal buchen" },
  { title: "Minus Bestand", code: "REMOVE", hint: "Abgang lokal buchen" },
  { title: "Nachkauf", code: "WISHLIST", hint: "Wunschliste markieren" },
  { title: "Abbrechen", code: "CANCEL", hint: "Scan-Session beenden" },
];

const state = {
  mode: new URLSearchParams(location.search).get("mode") || "overview",
  layout: null,
  slots: [],
  assignments: [],
};

const $ = (id) => document.getElementById(id);

async function api(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function assignmentForSlot(slotId) {
  return state.assignments.find((item) => item.drawer_id === slotId || item.slot_id === slotId);
}

function code128Values(code) {
  const text = String(code || "");
  const values = [104];
  for (const char of text) {
    const value = char.charCodeAt(0) - 32;
    if (value < 0 || value > 95) throw new Error(`Nicht druckbarer Barcode-Wert: ${char}`);
    values.push(value);
  }
  let checksum = values[0];
  for (let index = 1; index < values.length; index++) checksum += values[index] * index;
  values.push(checksum % 103, 106);
  return values;
}

function barcodeSvg(code) {
  const height = 52;
  let x = 0;
  const bars = [];
  for (const value of code128Values(code)) {
    const pattern = CODE128_PATTERNS[value];
    for (let index = 0; index < pattern.length; index++) {
      const width = Number(pattern[index]);
      if (index % 2 === 0) bars.push(`<rect x="${x}" y="0" width="${width}" height="${height}"></rect>`);
      x += width;
    }
  }
  return `<svg class="barcode" viewBox="0 0 ${x} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(code)}">${bars.join("")}</svg><div class="barcode-label">${escapeHtml(code)}</div>`;
}

function actionCards() {
  return `<section class="actions-grid">${ACTIONS.map((action) => `
    <article class="action-card">
      <b>${escapeHtml(action.title)}</b>
      <p>${escapeHtml(action.hint)}</p>
      ${barcodeSvg(action.code)}
    </article>
  `).join("")}</section>`;
}

function slotCard(slot) {
  const assignment = assignmentForSlot(slot.id);
  return `
    <article class="drawer-cell">
      <b>${escapeHtml(slot.label)}</b>
      <p class="part-name">${escapeHtml(assignment?.part_name || "Nicht zugeordnet")}</p>
      ${barcodeSvg(`DRAWER:${slot.id}`)}
    </article>
  `;
}

function renderOverview() {
  $("subtitle").textContent = "Grid-Übersicht mit Aktionscodes und Fach-Barcodes";
  const cabinets = state.layout.cabinets.map((cabinet) => {
    const slots = state.slots.filter((slot) => slot.cabinet_id === cabinet.id);
    return `
      <section class="cabinet-sheet">
        <div class="cabinet-head">
          <div>
            <h2>${escapeHtml(cabinet.name)}</h2>
            <p>${cabinet.rows} Reihen x ${cabinet.columns} Spalten · ${slots.length} Fächer</p>
          </div>
          <p>LED ab ${cabinet.start_led}</p>
        </div>
        <div class="drawer-grid" style="grid-template-columns: repeat(${Number(cabinet.columns || 1)}, minmax(28mm, 1fr));">
          ${slots.map(slotCard).join("")}
        </div>
      </section>
    `;
  }).join("");
  $("printRoot").innerHTML = `${actionCards()}${cabinets}`;
}

function labelCard(slot) {
  const assignment = assignmentForSlot(slot.id);
  const partBarcode = assignment?.partdb_part_id ? barcodeSvg(`PART:${assignment.partdb_part_id}`) : "";
  return `
    <article class="label-card" data-label-id="${escapeHtml(slot.id)}">
      <b>${escapeHtml(slot.label)}</b>
      <p class="part-name">${escapeHtml(assignment?.part_name || "Nicht zugeordnet")}</p>
      ${barcodeSvg(`DRAWER:${slot.id}`)}
      ${partBarcode}
      <div class="label-tools screen-only">
        <button data-print-label="${escapeHtml(slot.id)}">Einzeln drucken</button>
      </div>
    </article>
  `;
}

function renderLabels() {
  $("subtitle").textContent = "Einzelne Fach-Etiketten für Etikettendrucker";
  $("printRoot").innerHTML = `<section class="label-list">${state.slots.map(labelCard).join("")}</section>`;
  document.querySelectorAll("[data-print-label]").forEach((button) => {
    button.onclick = () => printOneLabel(button.dataset.printLabel);
  });
}

function renderActions() {
  $("subtitle").textContent = "Plus, Minus und weitere Aktions-Barcodes";
  $("printRoot").innerHTML = actionCards();
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.classList.toggle("primary", button.dataset.mode === mode);
  });
  document.body.classList.remove("print-one");
  document.querySelectorAll(".label-card").forEach((card) => card.dataset.printSelected = "false");
  if (mode === "labels") renderLabels();
  else if (mode === "actions") renderActions();
  else renderOverview();
}

function printOneLabel(slotId) {
  document.body.classList.add("print-one");
  document.querySelectorAll(".label-card").forEach((card) => {
    card.dataset.printSelected = card.dataset.labelId === slotId ? "true" : "false";
  });
  window.print();
}

async function init() {
  const layout = await api("/api/layout");
  state.layout = layout.layout;
  state.slots = layout.slots;
  state.assignments = await api("/api/assignments");
  document.querySelectorAll("[data-mode]").forEach((button) => {
    button.onclick = () => setMode(button.dataset.mode);
  });
  $("printBtn").onclick = () => window.print();
  setMode(state.mode);
}

init().catch((error) => {
  $("subtitle").textContent = "Druckdaten konnten nicht geladen werden.";
  $("printRoot").innerHTML = `<p>${escapeHtml(error.message)}</p>`;
});
