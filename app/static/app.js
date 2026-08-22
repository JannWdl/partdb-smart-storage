let state = { layout: null, slots: [], assignments: [], parts: [] };

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
  state.slots = layout.slots;
  state.assignments = await api("/api/assignments");
  renderMagazines();
  renderSlotSelect();
  renderAssignments();
  renderLayoutEditor();
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

function renderLayoutEditor() {
  const root = $("layoutEditor");
  root.innerHTML = "";
  state.layout.cabinets.forEach((cabinet, index) => {
    const card = document.createElement("div");
    card.className = "layout-card";
    card.innerHTML = `
      <div class="fields">
        <label>Name <input data-i="${index}" data-k="name" value="${cabinet.name}"></label>
        <label>ID <input data-i="${index}" data-k="id" value="${cabinet.id}"></label>
        <label>Reihen <input type="number" min="1" data-i="${index}" data-k="rows" value="${cabinet.rows}"></label>
        <label>Spalten <input type="number" min="1" data-i="${index}" data-k="columns" value="${cabinet.columns}"></label>
        <label>Start LED <input type="number" min="0" data-i="${index}" data-k="start_led" value="${cabinet.start_led}"></label>
        <label>LEDs/Fach <input type="number" min="1" data-i="${index}" data-k="leds_per_slot" value="${cabinet.leds_per_slot}"></label>
      </div>
      <label class="meta"><input type="checkbox" data-i="${index}" data-k="serpentine" ${cabinet.serpentine ? "checked" : ""}> Serpentine</label>
    `;
    root.appendChild(card);
  });
}

function collectLayout() {
  const layout = JSON.parse(JSON.stringify(state.layout));
  document.querySelectorAll("[data-i][data-k]").forEach((input) => {
    const cabinet = layout.cabinets[Number(input.dataset.i)];
    const key = input.dataset.k;
    if (input.type === "checkbox") cabinet[key] = input.checked;
    else if (["rows", "columns", "start_led", "leds_per_slot"].includes(key)) cabinet[key] = Number(input.value);
    else cabinet[key] = input.value.trim();
  });
  return layout;
}

async function locateSlot(slotId, mode = "locate") {
  const data = await api(`/api/slots/${encodeURIComponent(slotId)}/locate`, {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
  toast(`${data.slot.label} leuchtet: LED ${data.slot.led_start}-${data.slot.led_stop - 1}`);
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
$("addCabinetBtn").onclick = () => {
  state.layout.cabinets.push({
    id: `magazin-${state.layout.cabinets.length + 1}`,
    name: `Magazin ${state.layout.cabinets.length + 1}`,
    rows: 3,
    columns: 4,
    start_led: state.slots.reduce((max, slot) => Math.max(max, slot.led_stop), 0),
    leds_per_slot: 4,
    serpentine: false,
    slot_prefix: "Fach",
  });
  renderLayoutEditor();
};
$("saveLayoutBtn").onclick = async () => {
  const layout = collectLayout();
  await api("/api/layout", { method: "PUT", body: JSON.stringify({ layout }) });
  toast("Layout gespeichert.");
  await loadAll();
};

loadAll().catch((error) => toast(error.message));

