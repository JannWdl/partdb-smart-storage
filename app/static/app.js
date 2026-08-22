let state = { layout: null, draftLayout: null, slots: [], previewSlots: [], assignments: [], parts: [], setupStep: "arrangement" };

const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2600);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(body.error || response.statusText);
  }
  return response.json();
}

async function loadAll() {
  const layout = await api("/api/layout");
  state.layout = layout.layout;
  state.draftLayout = JSON.parse(JSON.stringify(layout.layout));
  state.slots = layout.slots;
  state.previewSlots = layout.slots;
  state.assignments = await api("/api/assignments");
  renderMagazines();
  renderSlotSelect();
  renderAssignments();
  renderSetupGuide();
  checkHealth();
}

async function checkHealth() {
  const health = await api("/api/health").catch(() => ({ partdb: false, wled: false }));
  $("health").textContent = `Part-DB ${health.partdb ? "online" : "nicht erreichbar"} · WLED ${health.wled ? "online" : "nicht erreichbar"}`;
}

function assignedBySlot(slotId) {
  return state.assignments.find((item) => item.slot_id === slotId);
}

function renderMagazines() {
  const root = $("magazines");
  root.innerHTML = "";
  for (const cabinet of state.layout.cabinets) {
    const slots = state.slots.filter((slot) => slot.cabinet_id === cabinet.id);
    const block = document.createElement("div");
    block.innerHTML = `<div class="cabinet-title"><h2>${cabinet.name}</h2><p>${cabinet.rows} x ${cabinet.columns} · Start LED ${cabinet.start_led}</p></div>`;
    const grid = document.createElement("div");
    grid.className = "cabinet-grid";
    grid.style.gridTemplateColumns = `repeat(${cabinet.columns}, minmax(74px, 1fr))`;
    for (const slot of slots) {
      const assignment = assignedBySlot(slot.id);
      const button = document.createElement("button");
      button.className = "slot";
      button.innerHTML = `${slot.label}<small>LED ${slot.led_start}-${slot.led_stop - 1}${assignment ? "<br>" + assignment.part_name : ""}</small>`;
      button.onclick = () => locateSlot(slot.id);
      grid.appendChild(button);
    }
    block.appendChild(grid);
    root.appendChild(block);
  }
}

function renderSlotSelect() {
  $("slotSelect").innerHTML = state.slots
    .map((slot) => `<option value="${slot.id}">${slot.label} · ${slot.cabinet_name} · LED ${slot.led_start}-${slot.led_stop - 1}</option>`)
    .join("");
}

function renderAssignments() {
  const root = $("assignments");
  if (!state.assignments.length) {
    root.innerHTML = `<p>Noch keine Zuordnung gespeichert.</p>`;
    return;
  }
  root.innerHTML = "";
  for (const item of state.assignments) {
    const row = document.createElement("div");
    row.className = "assignment-row";
    const slotText = item.slot ? `${item.slot.label} · LED ${item.slot.led_start}-${item.slot.led_stop - 1}` : "Layout-Fach fehlt";
    row.innerHTML = `<div><b>${item.part_name}</b><p>${slotText}</p></div>`;
    const locate = document.createElement("button");
    locate.textContent = "Zeigen";
    locate.onclick = () => locateSlot(item.slot_id);
    const remove = document.createElement("button");
    remove.textContent = "Loeschen";
    remove.onclick = async () => {
      await api(`/api/assignments/${encodeURIComponent(item.part_id)}`, { method: "DELETE" });
      toast("Zuordnung geloescht.");
      await loadAll();
    };
    row.appendChild(locate);
    row.appendChild(remove);
    root.appendChild(row);
  }
}

function computePreviewSlots(layout) {
  const slots = [];
  let globalIndex = 1;
  for (const cabinet of layout.cabinets) {
    const rows = Number(cabinet.rows || 1);
    const columns = Number(cabinet.columns || 1);
    const startLed = Number(cabinet.start_led || 0);
    const ledsPerSlot = Number(cabinet.leds_per_slot || 1);
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < columns; col++) {
        const physicalCol = cabinet.serpentine && row % 2 ? columns - 1 - col : col;
        const ledStart = startLed + ((row * columns + physicalCol) * ledsPerSlot);
        slots.push({
          id: `${cabinet.id}-${row + 1}-${col + 1}`,
          label: `${cabinet.slot_prefix || "Fach"} ${globalIndex}`,
          global_index: globalIndex,
          cabinet_id: cabinet.id,
          cabinet_name: cabinet.name,
          row: row + 1,
          column: col + 1,
          led_start: ledStart,
          led_stop: ledStart + ledsPerSlot,
          slot_width_mm: Number(cabinet.slot_width_mm || 0),
          slot_height_mm: Number(cabinet.slot_height_mm || 0),
        });
        globalIndex++;
      }
    }
  }
  return slots;
}

function renderSetupGuide() {
  const root = $("setupGuide");
  root.innerHTML = "";
  state.previewSlots = computePreviewSlots(state.draftLayout);
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.step === state.setupStep);
  });
  if (state.setupStep === "arrangement") renderArrangementStep(root);
  if (state.setupStep === "leds") renderLedStep(root);
  if (state.setupStep === "review") renderReviewStep(root);
}

function renderArrangementStep(root) {
  root.appendChild(helpText("Lege fest, aus welchen Magazinblöcken dein Schrank besteht. Ein Block kann ein normales Raster oder ein einzelnes großes Fach sein."));
  state.draftLayout.cabinets.forEach((cabinet, index) => {
    const card = document.createElement("div");
    card.className = "layout-card";
    card.innerHTML = `
      <div class="fields">
        <label>Name <input data-draft-i="${index}" data-k="name" value="${cabinet.name}"></label>
        <label>Kurz-ID <input data-draft-i="${index}" data-k="id" value="${cabinet.id}"></label>
        <label>Reihen <input type="number" min="1" data-draft-i="${index}" data-k="rows" value="${cabinet.rows}"></label>
        <label>Spalten <input type="number" min="1" data-draft-i="${index}" data-k="columns" value="${cabinet.columns}"></label>
        <label>Fachbreite mm <input type="number" min="0" data-draft-i="${index}" data-k="slot_width_mm" value="${cabinet.slot_width_mm || 0}"></label>
        <label>Fachhöhe mm <input type="number" min="0" data-draft-i="${index}" data-k="slot_height_mm" value="${cabinet.slot_height_mm || 0}"></label>
      </div>
      <div class="wizard-actions">
        <button data-remove-cabinet="${index}">Entfernen</button>
      </div>
    `;
    root.appendChild(card);
  });
  root.appendChild(actionButton("Magazinblock hinzufügen", addCabinet));
  root.appendChild(navButtons(null, "Weiter: LEDs"));
  bindDraftInputs();
}

function renderLedStep(root) {
  root.appendChild(helpText("Hier stellst du ein, wo der LED-Bereich jedes Blocks beginnt, wie viele LEDs zu einem Fach gehören und ob die Verkabelung schlangenförmig läuft."));
  state.draftLayout.cabinets.forEach((cabinet, index) => {
    const slots = state.previewSlots.filter((slot) => slot.cabinet_id === cabinet.id);
    const last = slots.reduce((max, slot) => Math.max(max, slot.led_stop - 1), 0);
    const card = document.createElement("div");
    card.className = "layout-card";
    card.innerHTML = `
      <h3>${cabinet.name}</h3>
      <div class="fields">
        <label>Start-LED <input type="number" min="0" data-draft-i="${index}" data-k="start_led" value="${cabinet.start_led}"></label>
        <label>LEDs pro Fach <input type="number" min="1" data-draft-i="${index}" data-k="leds_per_slot" value="${cabinet.leds_per_slot}"></label>
        <label>Fach-Beschriftung <input data-draft-i="${index}" data-k="slot_prefix" value="${cabinet.slot_prefix || "Fach"}"></label>
        <label class="checkline"><input type="checkbox" data-draft-i="${index}" data-k="serpentine" ${cabinet.serpentine ? "checked" : ""}> Serpentine</label>
      </div>
      <p class="meta">${slots.length} Fächer · LED ${cabinet.start_led}-${last} · ${cabinet.slot_width_mm || 0} x ${cabinet.slot_height_mm || 0} mm</p>
    `;
    root.appendChild(card);
  });
  root.appendChild(navButtons("Zurück", "Weiter: Test"));
  bindDraftInputs();
}

function renderReviewStep(root) {
  root.appendChild(helpText("Prüfe die berechneten Fächer. Ein Klick auf ein Fach lässt es direkt am WLED-Controller leuchten. Übernehmen speichert das Layout dauerhaft."));
  const summary = document.createElement("div");
  summary.className = "setup-summary";
  const totalSlots = state.previewSlots.length;
  const totalLeds = state.previewSlots.reduce((max, slot) => Math.max(max, slot.led_stop), 0);
  summary.innerHTML = `<b>${totalSlots} Fächer</b><span>${totalLeds} LEDs belegt</span>`;
  root.appendChild(summary);
  root.appendChild(renderPreviewGrid());
  root.appendChild(navButtons("Zurück", null));
  root.appendChild(actionButton("Layout übernehmen", saveDraftLayout, "primary"));
}

function renderPreviewGrid() {
  const wrap = document.createElement("div");
  wrap.className = "setup-preview";
  for (const cabinet of state.draftLayout.cabinets) {
    const block = document.createElement("div");
    const slots = state.previewSlots.filter((slot) => slot.cabinet_id === cabinet.id);
    block.innerHTML = `<div class="cabinet-title"><h3>${cabinet.name}</h3><p>${cabinet.rows} x ${cabinet.columns}</p></div>`;
    const grid = document.createElement("div");
    grid.className = "cabinet-grid";
    grid.style.gridTemplateColumns = `repeat(${cabinet.columns}, minmax(58px, 1fr))`;
    for (const slot of slots) {
      const button = document.createElement("button");
      button.className = "slot mini";
      button.innerHTML = `${slot.label}<small>${slot.led_start}-${slot.led_stop - 1}</small>`;
      button.onclick = () => locatePreviewSlot(slot);
      grid.appendChild(button);
    }
    block.appendChild(grid);
    wrap.appendChild(block);
  }
  return wrap;
}

function helpText(text) {
  const p = document.createElement("p");
  p.className = "setup-help";
  p.textContent = text;
  return p;
}

function actionButton(label, handler, kind = "") {
  const button = document.createElement("button");
  button.className = kind;
  button.textContent = label;
  button.onclick = handler;
  return button;
}

function navButtons(backLabel, nextLabel) {
  const row = document.createElement("div");
  row.className = "wizard-actions";
  if (backLabel) row.appendChild(actionButton(backLabel, previousSetupStep));
  if (nextLabel) row.appendChild(actionButton(nextLabel, nextSetupStep, "primary"));
  return row;
}

function bindDraftInputs() {
  document.querySelectorAll("[data-draft-i][data-k]").forEach((input) => {
    input.oninput = updateDraftFromInputs;
    input.onchange = updateDraftFromInputs;
  });
  document.querySelectorAll("[data-remove-cabinet]").forEach((button) => {
    button.onclick = () => {
      if (state.draftLayout.cabinets.length === 1) return toast("Mindestens ein Magazinblock bleibt erhalten.");
      state.draftLayout.cabinets.splice(Number(button.dataset.removeCabinet), 1);
      renderSetupGuide();
    };
  });
}

function updateDraftFromInputs() {
  document.querySelectorAll("[data-draft-i][data-k]").forEach((input) => {
    const cabinet = state.draftLayout.cabinets[Number(input.dataset.draftI)];
    const key = input.dataset.k;
    if (input.type === "checkbox") cabinet[key] = input.checked;
    else if (["rows", "columns", "start_led", "leds_per_slot", "slot_width_mm", "slot_height_mm"].includes(key)) cabinet[key] = Number(input.value);
    else if (key === "id") cabinet[key] = slug(input.value);
    else cabinet[key] = input.value.trim();
  });
  state.previewSlots = computePreviewSlots(state.draftLayout);
}

function slug(value) {
  return String(value || "magazin").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "magazin";
}

function setupStepIndex() {
  return ["arrangement", "leds", "review"].indexOf(state.setupStep);
}

function nextSetupStep() {
  updateDraftFromInputs();
  state.setupStep = ["arrangement", "leds", "review"][Math.min(setupStepIndex() + 1, 2)];
  renderSetupGuide();
}

function previousSetupStep() {
  updateDraftFromInputs();
  state.setupStep = ["arrangement", "leds", "review"][Math.max(setupStepIndex() - 1, 0)];
  renderSetupGuide();
}

function addCabinet() {
  updateDraftFromInputs();
  state.draftLayout.cabinets.push({
    id: `magazin-${state.draftLayout.cabinets.length + 1}`,
    name: `Magazin ${state.draftLayout.cabinets.length + 1}`,
    rows: 3,
    columns: 4,
    start_led: state.previewSlots.reduce((max, slot) => Math.max(max, slot.led_stop), 0),
    leds_per_slot: 4,
    slot_width_mm: 55,
    slot_height_mm: 38,
    serpentine: false,
    slot_prefix: "Fach",
  });
  renderSetupGuide();
}

async function locateSlot(slotId, mode = "locate") {
  const data = await api(`/api/slots/${encodeURIComponent(slotId)}/locate`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  toast(`${data.slot.label} leuchtet: LED ${data.slot.led_start}-${data.slot.led_stop - 1}`);
}

async function locatePreviewSlot(slot) {
  const existing = state.slots.find((item) => item.id === slot.id && item.led_start === slot.led_start && item.led_stop === slot.led_stop);
  if (existing) return locateSlot(existing.id);
  await api("/api/wled/range", {
    method: "POST",
    body: JSON.stringify({ start: slot.led_start, stop: slot.led_stop, mode: "test" }),
  });
  toast(`${slot.label} Test: LED ${slot.led_start}-${slot.led_stop - 1}`);
}

async function searchParts() {
  const query = $("partSearch").value.trim();
  if (!query) return;
  const parts = await api(`/api/partdb/search?q=${encodeURIComponent(query)}`);
  state.parts = parts;
  $("partSelect").innerHTML = parts.length
    ? parts.map((part) => `<option value="${part.id}">${part.name}</option>`).join("")
    : `<option value="">Keine Part-DB-Treffer</option>`;
  toast(parts.length ? `${parts.length} Treffer gefunden.` : "Keine Treffer.");
}

async function assignSelected() {
  const selected = $("partSelect").selectedOptions[0];
  if (!selected || !selected.value) throw new Error("Bitte erst ein Teil suchen.");
  await api("/api/assignments", {
    method: "POST",
    body: JSON.stringify({
      part_id: selected.value,
      part_name: selected.textContent,
      slot_id: $("slotSelect").value,
      notes: $("notes").value,
    }),
  });
  toast("Gespeichert und Fach getestet.");
  await loadAll();
}

async function findAssignment() {
  const query = $("findInput").value.trim();
  if (!query) return;
  const result = await api(`/api/find?q=${encodeURIComponent(query)}`).catch(() => null);
  toast(result && result.found ? `${result.assignment.part_name} gefunden.` : "Keine Zuordnung gefunden.");
}

$("partSearchBtn").onclick = () => searchParts().catch((error) => toast(error.message));
$("assignBtn").onclick = () => assignSelected().catch((error) => toast(error.message));
$("findBtn").onclick = () => findAssignment().catch((error) => toast(error.message));
$("offBtn").onclick = () => api("/api/wled/off", { method: "POST" }).then(() => toast("LEDs aus."));
async function saveDraftLayout() {
  updateDraftFromInputs();
  await api("/api/layout", { method: "PUT", body: JSON.stringify({ layout: state.draftLayout }) });
  toast("Layout gespeichert.");
  await loadAll();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    updateDraftFromInputs();
    state.setupStep = tab.dataset.step;
    renderSetupGuide();
  };
});

loadAll().catch((error) => toast(error.message));
