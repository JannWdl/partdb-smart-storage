let state = {
  layout: null,
  draftLayout: null,
  slots: [],
  previewSlots: [],
  assignments: [],
  parts: [],
  settings: null,
  stockEvents: [],
  scanSession: null,
  setupStep: "arrangement",
  setupModalShown: false,
  activePanel: "assignPanel",
  selectedCabinetId: null,
  cameraStream: null,
  cameraTimer: null,
  lastCameraCode: "",
  lastCameraAt: 0,
  keyboardScanBuffer: "",
  keyboardScanAt: 0,
  lastScanStatus: "",
};

const $ = (id) => document.getElementById(id);

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2600);
}

function setupSeen() {
  try {
    return localStorage.getItem("smart-storage-setup-seen") === "1";
  } catch {
    return false;
  }
}

function rememberSetupSeen() {
  try {
    localStorage.setItem("smart-storage-setup-seen", "1");
  } catch {
    // The assistant can still be opened from the setup tab.
  }
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: response.statusText }));
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail || response.statusText);
    throw new Error(body.error || body.detail?.message || detail);
  }
  return response.json();
}

async function loadAll() {
  const layout = await api("/api/layout");
  state.layout = layout.layout;
  state.draftLayout = JSON.parse(JSON.stringify(layout.layout));
  normalizeCabinetPositions(state.draftLayout);
  state.selectedCabinetId = state.selectedCabinetId || state.draftLayout.cabinets[0]?.id || null;
  state.slots = layout.slots;
  state.previewSlots = layout.slots;
  state.assignments = await api("/api/assignments");
  state.settings = await api("/api/settings");
  state.stockEvents = await api("/api/stock/events?limit=20");
  state.scanSession = await api("/api/scan/session").catch(() => ({ session: null }));
  renderMagazines();
  renderSlotSelect();
  renderAssignments();
  renderSettingsPanel();
  renderBarcodePanel();
  renderPrintPanel();
  renderSetupGuide();
  renderSideTabs();
  checkHealth();
  if (!state.setupModalShown && !setupSeen()) {
    state.setupModalShown = true;
    openSetupModal();
  }
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

function renderSettingsPanel() {
  const root = $("settingsPanel");
  const cfg = state.settings || {};
  root.innerHTML = `
    <div class="fields settings-fields">
      <label>Part-DB URL <input id="settingPartdbUrl" value="${cfg.partdb_url || ""}"></label>
      <label>Part-DB intern <input id="settingPartdbInternalUrl" value="${cfg.partdb_internal_url || ""}"></label>
      <label>API-Token <input id="settingPartdbToken" type="password" placeholder="${cfg.partdb_api_token_configured ? "Gesetzt - leer lassen zum Behalten" : "Kein Token gesetzt"}"></label>
      <p class="meta token-state">${cfg.partdb_api_token_configured ? "Part-DB Token ist gesetzt." : "Part-DB Token fehlt. Bitte setup-partdb-admin.sh ausfuehren oder Token eintragen."}</p>
      <label>WLED URL <input id="settingWledUrl" value="${cfg.wled_url || ""}"></label>
      <label>Scan-Timeout s <input id="settingTimeout" type="number" min="5" max="300" value="${cfg.scan_timeout_seconds || 30}"></label>
      <label class="checkline"><input id="settingBarcodeEnabled" type="checkbox" ${cfg.barcode_enabled ? "checked" : ""}> Barcode aktiv</label>
      <label class="checkline"><input id="settingCameraEnabled" type="checkbox" ${cfg.barcode_camera_enabled ? "checked" : ""}> Kamera-Scanner aktiv</label>
      <label class="checkline"><input id="settingStockWriteEnabled" type="checkbox" ${cfg.partdb_stock_write_enabled ? "checked" : ""}> Part-DB Bestand schreiben</label>
    </div>
    <div class="wizard-actions">
      <button id="saveSettingsBtn" class="primary">Speichern</button>
      <button id="testWledBtn">WLED testen</button>
      <button id="testPartdbStockBtn">Part-DB Buchung testen</button>
    </div>
  `;
  $("saveSettingsBtn").onclick = saveSettings;
  $("testWledBtn").onclick = testWled;
  $("testPartdbStockBtn").onclick = () => testPartdbStock().catch((error) => toast(error.message));
}

function renderSideTabs() {
  document.querySelectorAll(".side-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.panel === state.activePanel);
    button.onclick = () => {
      if (button.dataset.panel === "setupModal") {
        openSetupModal();
        return;
      }
      state.activePanel = button.dataset.panel;
      renderSideTabs();
    };
  });
  document.querySelectorAll(".side-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === state.activePanel);
  });
}

function openSetupModal() {
  $("setupModal").classList.add("open");
  renderSetupGuide();
}

function closeSetupModal() {
  rememberSetupSeen();
  $("setupModal").classList.remove("open");
}

function renderBarcodePanel() {
  const cfg = state.settings || {};
  const session = state.scanSession?.session || {};
  const root = $("barcodePanel");
  root.innerHTML = `
    <p class="meta">Barcode wird ausschließlich in den Einstellungen aktiviert oder deaktiviert.</p>
    <p class="meta">Codes: PART:&lt;id&gt;, DRAWER:&lt;fach-id&gt;, ADD, REMOVE, WISHLIST, CANCEL</p>
    <p class="meta">USB-Scanner funktionieren wie eine Tastatur. Deutsches Layout wird automatisch korrigiert, zum Beispiel PARTÖ123 zu PART:123.</p>
    <div class="scan-context">
      <div><span>Teil</span><b>${session.part_name || session.partdb_part_id || "nicht gewählt"}</b></div>
      <div><span>Fach</span><b>${session.drawer_id || "nicht gewählt"}</b></div>
      <div><span>Modus</span><b>${cfg.partdb_stock_write_enabled ? "Part-DB schreiben" : "Testmodus lokal"}</b></div>
    </div>
    <div class="form-grid barcode-line">
      <input id="scanInput" placeholder="Scanner-Fokus: Barcode scannen oder eintippen" ${cfg.barcode_enabled ? "" : "disabled"}>
      <button id="scanBtn" ${cfg.barcode_enabled ? "" : "disabled"}>Senden</button>
    </div>
    <p class="meta">Tipp: Barcode-Tab öffnen und scannen. Das Feld muss nicht zwingend fokussiert sein, solange der Scanner am Ende Enter sendet.</p>
    <div class="stock-buttons">
      <button data-scan-code="ADD" class="success" ${cfg.barcode_enabled ? "" : "disabled"}>+ Bestand</button>
      <button data-scan-code="REMOVE" class="danger" ${cfg.barcode_enabled ? "" : "disabled"}>- Bestand</button>
      <button data-scan-code="WISHLIST" ${cfg.barcode_enabled ? "" : "disabled"}>Nachkauf</button>
      <button data-scan-code="CANCEL" ${cfg.barcode_enabled ? "" : "disabled"}>Abbrechen</button>
    </div>
    <div class="wizard-actions">
      <button id="cameraBtn" ${cfg.barcode_enabled && cfg.barcode_camera_enabled ? "" : "disabled"}>Kamera starten</button>
      <button id="cameraStopBtn">Kamera stoppen</button>
    </div>
    <video id="cameraPreview" muted playsinline></video>
    <div id="scanStatus" class="status-line"></div>
    <div id="stockEvents"></div>
  `;
  $("scanBtn").onclick = () => sendScan($("scanInput").value).catch((error) => showScanError(error.message));
  $("scanInput").onkeydown = (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      sendScan(event.currentTarget.value).catch((error) => showScanError(error.message));
    }
  };
  $("cameraBtn").onclick = () => startCameraScanner().catch((error) => showScanError(error.message));
  $("cameraStopBtn").onclick = stopCameraScanner;
  root.querySelectorAll("[data-scan-code]").forEach((button) => {
    button.onclick = () => sendScan(button.dataset.scanCode).catch((error) => showScanError(error.message));
  });
  $("scanStatus").textContent = state.lastScanStatus;
  renderStockEvents();
}

function printUrl(mode) {
  return `/static/print.html?mode=${encodeURIComponent(mode)}`;
}

function renderPrintPanel() {
  const root = $("printPanel");
  root.innerHTML = `
    <p class="meta">Druckt Barcodes direkt aus deinem aktuellen Layout und deinen gespeicherten Zuordnungen.</p>
    <div class="print-actions">
      <button data-print-mode="overview" class="primary">Grid-Übersicht</button>
      <button data-print-mode="labels">Einzel-Etiketten</button>
      <button data-print-mode="actions">Plus / Minus / Aktionen</button>
    </div>
    <p class="meta">Für Etikettendrucker: Einzel-Etiketten öffnen und beim gewünschten Fach auf „Einzeln drucken“ klicken.</p>
  `;
  root.querySelectorAll("[data-print-mode]").forEach((button) => {
    button.onclick = () => window.open(printUrl(button.dataset.printMode), "_blank", "noopener");
  });
}

function showScanError(message) {
  beep("error");
  state.lastScanStatus = message;
  $("scanStatus").textContent = message;
  toast(message);
}

function renderStockEvents() {
  const root = $("stockEvents");
  if (!state.stockEvents.length) {
    root.innerHTML = `<p class="meta">Noch keine lokalen Buchungen.</p>`;
    return;
  }
  root.innerHTML = state.stockEvents.map((event) => `
    <div class="event-row">
      <b>${event.event_type}</b>
      <span>${event.part_name || event.partdb_part_id || "ohne Teil"}</span>
      <small>${event.status || "local"}${event.drawer_id ? " · " + event.drawer_id : ""}</small>
      ${event.sync_error ? `<em>${event.sync_error}</em>` : ""}
    </div>
  `).join("");
}

async function saveSettings() {
  state.settings = await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify({
      partdb_url: $("settingPartdbUrl").value,
      partdb_internal_url: $("settingPartdbInternalUrl").value,
      partdb_api_token: $("settingPartdbToken").value,
      wled_url: $("settingWledUrl").value,
      scan_timeout_seconds: Number($("settingTimeout").value || 30),
      barcode_enabled: $("settingBarcodeEnabled").checked,
      barcode_camera_enabled: $("settingCameraEnabled").checked,
      partdb_stock_write_enabled: $("settingStockWriteEnabled").checked,
    }),
  });
  toast("Einstellungen gespeichert.");
  await checkHealth();
  renderSettingsPanel();
  renderBarcodePanel();
}

async function testPartdbStock() {
  const result = await api("/api/partdb/stock/test");
  if (!result.ok) throw new Error(result.message || "Part-DB Buchung nicht bereit.");
  beep("success");
  toast(result.message || "Part-DB Buchung bereit.");
}

async function testWled() {
  await api("/api/wled/test", {
    method: "POST",
    body: JSON.stringify({ wled_url: $("settingWledUrl").value }),
  });
  beep("success");
  toast("WLED ist erreichbar.");
}

function beep(kind) {
  try {
    const context = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const freq = { success: 880, error: 180, wishlist: 520, locate: 660 }[kind] || 440;
    oscillator.frequency.value = freq;
    gain.gain.value = 0.06;
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.12);
  } catch {
    // Audio feedback is best-effort only.
  }
}

function normalizeScanCode(rawCode) {
  let code = String(rawCode || "").trim();
  code = code.replace(/[\r\n\t ]+/g, "");
  code = code.replace(/[：;]/g, ":");
  code = code.replace(/[Öö]/g, ":");
  code = code.replace(/^PART[:：;Öö]?/i, "PART:");
  code = code.replace(/^DRAWER[:：;Öö]?/i, "DRAWER:");
  const upper = code.toUpperCase();
  if (["ADD", "REMOVE", "WISHLIST", "CANCEL"].includes(upper)) return upper;
  return code;
}

async function sendScan(rawCode) {
  const code = normalizeScanCode(rawCode);
  if (!code) return;
  $("scanInput").value = "";
  const result = await api("/api/scan", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  beep(result.audio || result.kind || (result.ok ? "success" : "error"));
  state.lastScanStatus = result.message || "Scan verarbeitet.";
  $("scanStatus").textContent = state.lastScanStatus;
  toast(state.lastScanStatus);
  state.scanSession = await api("/api/scan/session").catch(() => ({ session: result.session || null }));
  state.stockEvents = await api("/api/stock/events?limit=20");
  renderBarcodePanel();
  renderStockEvents();
}

function shouldCaptureScannerKey(event) {
  if (state.activePanel !== "barcodeSection") return false;
  if (!state.settings?.barcode_enabled) return false;
  if (event.ctrlKey || event.altKey || event.metaKey) return false;
  const target = event.target;
  if (target?.id === "scanInput") return false;
  if (target?.tagName === "TEXTAREA" || target?.isContentEditable) return false;
  if (target?.tagName === "INPUT" && target.type !== "button") return false;
  return event.key === "Enter" || event.key.length === 1;
}

function handleScannerKeyboard(event) {
  if (!shouldCaptureScannerKey(event)) return;
  const now = Date.now();
  if (now - state.keyboardScanAt > 250) state.keyboardScanBuffer = "";
  state.keyboardScanAt = now;
  if (event.key === "Enter") {
    const code = state.keyboardScanBuffer;
    state.keyboardScanBuffer = "";
    if (code) {
      event.preventDefault();
      sendScan(code).catch((error) => showScanError(error.message));
    }
    return;
  }
  state.keyboardScanBuffer += event.key;
  if (state.keyboardScanBuffer.length > 128) {
    state.keyboardScanBuffer = state.keyboardScanBuffer.slice(-128);
  }
}

async function startCameraScanner() {
  if (!("BarcodeDetector" in window)) {
    $("scanStatus").textContent = "Dieser Browser unterstützt BarcodeDetector nicht. USB-Scanner oder Chrome/Android verwenden.";
    beep("error");
    return;
  }
  const video = $("cameraPreview");
  state.cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
  video.srcObject = state.cameraStream;
  await video.play();
  const detector = new BarcodeDetector({ formats: ["qr_code", "code_128", "ean_13", "ean_8"] });
  state.cameraTimer = window.setInterval(async () => {
    try {
      const codes = await detector.detect(video);
      if (codes.length) {
        const value = codes[0].rawValue;
        const now = Date.now();
        if (value !== state.lastCameraCode || now - state.lastCameraAt > 2500) {
          state.lastCameraCode = value;
          state.lastCameraAt = now;
          await sendScan(value);
        }
      }
    } catch {
      stopCameraScanner();
      $("scanStatus").textContent = "Kamera-Scan wurde gestoppt.";
    }
  }, 900);
}

function stopCameraScanner() {
  if (state.cameraTimer) window.clearInterval(state.cameraTimer);
  state.cameraTimer = null;
  if (state.cameraStream) state.cameraStream.getTracks().forEach((track) => track.stop());
  state.cameraStream = null;
  const video = $("cameraPreview");
  if (video) video.srcObject = null;
}

function computePreviewSlots(layout) {
  const slots = [];
  let globalIndex = 1;
  for (const cabinet of layout.cabinets) {
    const rows = Number(cabinet.rows || 1);
    const columns = Number(cabinet.columns || 1);
    const startLed = Number(cabinet.start_led || 0);
    const ledsPerSlot = Number(cabinet.leds_per_slot || 1);
    const stripPath = cabinet.strip_path || cabinet.wiring_order || "rows";
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < columns; col++) {
        let pathIndex;
        if (stripPath === "columns") {
          const pathRow = cabinet.serpentine && col % 2 ? rows - 1 - row : row;
          pathIndex = col * rows + pathRow;
        } else {
          const pathCol = cabinet.serpentine && row % 2 ? columns - 1 - col : col;
          pathIndex = row * columns + pathCol;
        }
        const ledStart = startLed + (pathIndex * ledsPerSlot);
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
  root.appendChild(helpText("Ziehe Magazinblöcke auf der Fläche an die richtige Position. Klicke einen Block an, um Reihen, Spalten und Fachgröße zu ändern."));
  root.appendChild(renderVisualDesigner());
  root.appendChild(renderSelectedCabinetPanel());
  const quick = document.createElement("div");
  quick.className = "wizard-actions";
  quick.appendChild(actionButton("Raster hinzufügen", () => addCabinet("grid")));
  quick.appendChild(actionButton("Großes Fach hinzufügen", () => addCabinet("large")));
  root.appendChild(quick);
  root.appendChild(navButtons(null, "Weiter: LEDs"));
  bindDraftInputs();
}

function normalizeCabinetPositions(layout) {
  layout.cabinets.forEach((cabinet, index) => {
    if (cabinet.x == null) cabinet.x = 24 + (index % 2) * 180;
    if (cabinet.y == null) cabinet.y = 24 + Math.floor(index / 2) * 180;
    if (!cabinet.slot_width_mm) cabinet.slot_width_mm = cabinet.columns === 1 ? 220 : 55;
    if (!cabinet.slot_height_mm) cabinet.slot_height_mm = cabinet.rows === 1 ? 55 : 38;
  });
}

function cabinetPixelSize(cabinet) {
  const width = Math.max(88, Math.min(340, Number(cabinet.columns) * Math.max(28, Number(cabinet.slot_width_mm || 55) * 0.55)));
  const height = Math.max(58, Math.min(260, Number(cabinet.rows) * Math.max(28, Number(cabinet.slot_height_mm || 38) * 0.7)));
  return { width, height };
}

function renderVisualDesigner() {
  normalizeCabinetPositions(state.draftLayout);
  const board = document.createElement("div");
  board.className = "visual-board";
  for (const cabinet of state.draftLayout.cabinets) {
    const index = state.draftLayout.cabinets.indexOf(cabinet);
    const size = cabinetPixelSize(cabinet);
    const block = document.createElement("button");
    block.type = "button";
    block.className = `design-block${cabinet.id === state.selectedCabinetId ? " selected" : ""}`;
    block.style.left = `${Number(cabinet.x || 0)}px`;
    block.style.top = `${Number(cabinet.y || 0)}px`;
    block.style.width = `${size.width}px`;
    block.style.height = `${size.height}px`;
    block.dataset.cabinetId = cabinet.id;
    block.innerHTML = `
      <span>${cabinet.name}</span>
      <small>${cabinet.rows} x ${cabinet.columns}</small>
      <i style="grid-template-columns:repeat(${cabinet.columns},1fr)">${Array.from({ length: Number(cabinet.rows) * Number(cabinet.columns) }).map(() => "<b></b>").join("")}</i>
    `;
    block.onpointerdown = (event) => startCabinetDrag(event, index, block, board);
    board.appendChild(block);
  }
  return board;
}

function startCabinetDrag(event, index, block, board) {
  event.preventDefault();
  const cabinet = state.draftLayout.cabinets[index];
  state.selectedCabinetId = cabinet.id;
  document.querySelectorAll(".design-block").forEach((item) => item.classList.toggle("selected", item === block));
  const startX = event.clientX;
  const startY = event.clientY;
  const originX = Number(cabinet.x || 0);
  const originY = Number(cabinet.y || 0);
  const size = cabinetPixelSize(cabinet);
  block.setPointerCapture(event.pointerId);
  block.onpointermove = (moveEvent) => {
    const maxX = Math.max(0, board.clientWidth - size.width - 6);
    const maxY = Math.max(0, board.clientHeight - size.height - 6);
    cabinet.x = Math.round(Math.min(maxX, Math.max(0, originX + moveEvent.clientX - startX)));
    cabinet.y = Math.round(Math.min(maxY, Math.max(0, originY + moveEvent.clientY - startY)));
    block.style.left = `${cabinet.x}px`;
    block.style.top = `${cabinet.y}px`;
  };
  block.onpointerup = () => {
    block.onpointermove = null;
    block.onpointerup = null;
    renderSetupGuide();
  };
}

function renderSelectedCabinetPanel() {
  const index = Math.max(0, state.draftLayout.cabinets.findIndex((cabinet) => cabinet.id === state.selectedCabinetId));
  const cabinet = state.draftLayout.cabinets[index];
  const card = document.createElement("div");
  card.className = "layout-card inspector";
  card.innerHTML = `
    <h3>${cabinet.name}</h3>
    <div class="fields">
      <label>Name <input data-draft-i="${index}" data-k="name" value="${cabinet.name}"></label>
      <label>Kurz-ID <input data-draft-i="${index}" data-k="id" value="${cabinet.id}"></label>
      <label>Reihen <input type="number" min="1" data-draft-i="${index}" data-k="rows" value="${cabinet.rows}"></label>
      <label>Spalten <input type="number" min="1" data-draft-i="${index}" data-k="columns" value="${cabinet.columns}"></label>
      <label>Fachbreite mm <input type="number" min="0" data-draft-i="${index}" data-k="slot_width_mm" value="${cabinet.slot_width_mm || 0}"></label>
      <label>Fachhöhe mm <input type="number" min="0" data-draft-i="${index}" data-k="slot_height_mm" value="${cabinet.slot_height_mm || 0}"></label>
      <label>X <input type="number" min="0" data-draft-i="${index}" data-k="x" value="${cabinet.x || 0}"></label>
      <label>Y <input type="number" min="0" data-draft-i="${index}" data-k="y" value="${cabinet.y || 0}"></label>
    </div>
    <div class="wizard-actions">
      <button data-remove-cabinet="${index}">Entfernen</button>
    </div>
  `;
  return card;
}

function renderLedStep(root) {
  root.appendChild(helpText("Hier stellst du den fortlaufenden LED-Stripe ein: Start-LED, LEDs pro Fach, Laufweg durch die Fächer und optionalen Schlangenlauf."));
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
        <label>Strip-Verlauf <select data-draft-i="${index}" data-k="strip_path"><option value="rows" ${(cabinet.strip_path || cabinet.wiring_order) !== "columns" ? "selected" : ""}>Reihe für Reihe</option><option value="columns" ${(cabinet.strip_path || cabinet.wiring_order) === "columns" ? "selected" : ""}>Spalte für Spalte</option></select></label>
        <label class="checkline"><input type="checkbox" data-draft-i="${index}" data-k="serpentine" ${cabinet.serpentine ? "checked" : ""}> Serpentine / Schlangenlauf</label>
      </div>
      <p class="meta">${slots.length} Fächer · LED ${cabinet.start_led}-${last} · fortlaufender Stripe · ${cabinet.slot_width_mm || 0} x ${cabinet.slot_height_mm || 0} mm</p>
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
    else if (["rows", "columns", "start_led", "leds_per_slot", "slot_width_mm", "slot_height_mm", "x", "y"].includes(key)) cabinet[key] = Number(input.value);
    else if (key === "id") {
      const oldId = cabinet.id;
      cabinet[key] = slug(input.value);
      if (state.selectedCabinetId === oldId) state.selectedCabinetId = cabinet[key];
    } else cabinet[key] = input.value.trim();
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

function addCabinet(kind = "grid") {
  updateDraftFromInputs();
  const next = state.draftLayout.cabinets.length + 1;
  const isLarge = kind === "large";
  const startLed = state.previewSlots.reduce((max, slot) => Math.max(max, slot.led_stop), 0);
  const cabinet = {
    id: isLarge ? `grossfach-${next}` : `magazin-${next}`,
    name: isLarge ? `Großes Fach ${next}` : `Magazin ${next}`,
    rows: isLarge ? 1 : 3,
    columns: isLarge ? 1 : 4,
    start_led: startLed,
    leds_per_slot: isLarge ? 16 : 4,
    slot_width_mm: isLarge ? 220 : 55,
    slot_height_mm: isLarge ? 55 : 38,
    x: 24 + (next % 2) * 160,
    y: 24 + Math.floor(next / 2) * 130,
    strip_path: "rows",
    serpentine: false,
    slot_prefix: "Fach",
  };
  state.draftLayout.cabinets.push({
    ...cabinet,
  });
  state.selectedCabinetId = cabinet.id;
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
  const parts = await api(`/api/partdb/search?q=${encodeURIComponent(query)}`);
  state.parts = parts;
  $("partSelect").innerHTML = parts.length
    ? parts.map((part) => `<option value="${part.id}">${part.name} (#${part.id})</option>`).join("")
    : `<option value="">Keine Part-DB-Treffer</option>`;
  toast(parts.length ? `${parts.length} Teil(e) geladen.` : "Keine Teile in Part-DB gefunden.");
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
document.addEventListener("keydown", handleScannerKeyboard);
async function saveDraftLayout() {
  updateDraftFromInputs();
  await api("/api/layout", { method: "PUT", body: JSON.stringify({ layout: state.draftLayout }) });
  toast("Layout gespeichert.");
  closeSetupModal();
  await loadAll();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => {
    updateDraftFromInputs();
    state.setupStep = tab.dataset.step;
    renderSetupGuide();
  };
});

$("closeSetupBtn").onclick = closeSetupModal;

loadAll().catch((error) => toast(error.message));
