const hivesEl = document.querySelector("#hives");
const eventsEl = document.querySelector("#events");
const updatedEl = document.querySelector("#updated");
const alertEl = document.querySelector("#alert");
const soundButton = document.querySelector("#sound-toggle");
const demoButton = document.querySelector("#demo-button");
const eventFilter = document.querySelector("#event-filter");
const reportSelect = document.querySelector("#report-select");
const hiveForm = document.querySelector("#hive-form");
const managedHives = document.querySelector("#managed-hives");
let soundEnabled = true;
let lastCriticalId = null;
let latestEvents = [];
let latestReports = [];
let latestHives = [];
let selectedHiveId = null;

const labels = { normal: "Normal", uyari: "Uyarı", kritik: "Kritik", veri_yok: "Veri yok" };
const colors = { normal: "#15803d", uyari: "#b7791f", kritik: "#c62828", veri_yok: "#6d7685" };
const hiveNames = { H1: "Bahçe Kovanı", H2: "Orman Kovanı", H3: "Deneme Kovanı" };

function hiveLabel(hiveId) {
  return `${hiveNames[hiveId] || "Kovan"} (${hiveId})`;
}

function hiveColor(hiveId) {
  const colors = ["#15803d", "#b7791f", "#c62828", "#2563eb", "#7c3aed", "#0f766e"];
  const number = Number(hiveId.slice(1)) || 1;
  return colors[(number - 1) % colors.length];
}

function explainHiveIds(text) {
  return Object.keys(hiveNames).reduce(
    (result, hiveId) => result.replace(new RegExp(`\\b${hiveId}\\b`, "g"), hiveLabel(hiveId)),
    text
  );
}

function dateLabel(value) {
  if (!value) return "Henüz sinyal yok";
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

function beep() {
  if (!soundEnabled) return;
  const context = new AudioContext();
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.frequency.value = 760;
  gain.gain.setValueAtTime(.12, context.currentTime);
  gain.gain.exponentialRampToValueAtTime(.001, context.currentTime + .45);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start(); oscillator.stop(context.currentTime + .45);
}

function render(data) {
  latestEvents = data.events;
  latestHives = data.hives;
  data.hives.forEach(hive => { hiveNames[hive.hive_id] = hive.name; });
  const counts = data.hives.reduce((result, hive) => {
    result[hive.durum] = (result[hive.durum] || 0) + 1;
    return result;
  }, {});
  document.querySelector("#summary-total").textContent = data.hives.length;
  document.querySelector("#summary-normal").textContent = counts.normal || 0;
  document.querySelector("#summary-warning").textContent = counts.uyari || 0;
  document.querySelector("#summary-critical").textContent = counts.kritik || 0;
  hivesEl.innerHTML = data.hives.map(hive => `
    <article class="hive-card" style="--status:${colors[hive.durum]}">
      <div class="hive-head"><span class="hive-name">${escapeHtml(hive.name)}<small>${hive.hive_id}${hive.location ? ` · ${escapeHtml(hive.location)}` : ""}</small></span><span class="badge">${labels[hive.durum]}</span></div>
      <div class="confidence">${hive.confidence == null ? "—" : Math.round(hive.confidence * 100) + "%"}</div>
      <div class="confidence-label">model güveni</div>
      <div class="event-time">${dateLabel(hive.timestamp)}</div>
      <button class="hive-detail-button" data-hive-detail="${hive.hive_id}" type="button">Detayları gör <span>→</span></button>
    </article>`).join("");

  if (selectedHiveId) renderHiveDetail();
  renderManagedHives();
  updatedEl.textContent = `Son güncelleme ${dateLabel(data.generated_at)}`;

  const critical = data.events.find(event => event.event === "queenless_suspected" && event.confidence >= .85);
  if (critical && critical.id !== lastCriticalId) {
    lastCriticalId = critical.id;
    alertEl.textContent = `${hiveLabel(critical.hive_id)}: Ana arı kaybı şüphesi (${Math.round(critical.confidence * 100)}%)`;
    alertEl.classList.add("show"); beep();
    setTimeout(() => alertEl.classList.remove("show"), 5500);
  }
}

function renderEvents() {
  const filtered = latestEvents.filter(event =>
    (!selectedHiveId || event.hive_id === selectedHiveId) &&
    (eventFilter.value === "all" || event.event === eventFilter.value)
  );
  eventsEl.innerHTML = filtered.length ? filtered.map(event => `
    <tr><td>${dateLabel(event.timestamp)}</td><td>${hiveLabel(event.hive_id)}</td>
    <td class="${event.event === "queenless_suspected" ? "event-critical" : ""}">${event.event === "queenless_suspected" ? "Ana arı kaybı şüphesi" : event.event === "uncertain" ? "Belirsiz" : "Normal"}</td>
    <td>${Math.round(event.confidence * 100)}%</td>
    <td>${event.event !== "queenless_suspected" ? "—" : event.acknowledged_at ? '<span class="acknowledged">Kontrol edildi</span>' : `<button class="ack-button" data-ack="${event.id}" type="button">Kontrol edildi olarak işaretle</button>`}</td></tr>`).join("") : '<tr><td colspan="5">Filtreyle eşleşen olay yok.</td></tr>';
}

function renderChart(events) {
  const svg = document.querySelector("#confidence-chart");
  const grid = [0, 25, 50, 75, 100].map(value => {
    const y = 195 - value * 1.7;
    return `<line class="grid-line" x1="45" y1="${y}" x2="885" y2="${y}"/><text class="axis-label" x="5" y="${y + 4}">%${value}</text>`;
  }).join("");
  const hiveIds = selectedHiveId ? [selectedHiveId] : latestHives.map(hive => hive.hive_id);
  const series = hiveIds.map(hiveId => {
    const values = events.filter(event => event.hive_id === hiveId).slice(0, 12).reverse();
    if (!values.length) return "";
    const points = values.map((event, index) => {
      const x = values.length === 1 ? 465 : 55 + index * (820 / (values.length - 1));
      return { x, y: 195 - event.confidence * 170 };
    });
    const color = hiveColor(hiveId);
    return `<polyline class="chart-line" stroke="${color}" points="${points.map(point => `${point.x},${point.y}`).join(" ")}"/>${points.map(point => `<circle class="chart-point" fill="${color}" cx="${point.x}" cy="${point.y}" r="6"/>`).join("")}`;
  }).join("");
  svg.innerHTML = grid + (series || '<text class="chart-empty" x="450" y="110">Grafik için olay bekleniyor</text>');
}

function renderHiveDetail() {
  const hive = latestHives.find(item => item.hive_id === selectedHiveId);
  if (!hive) return;
  document.querySelector("#detail-title").textContent = hiveLabel(hive.hive_id);
  const status = document.querySelector("#detail-status");
  status.textContent = labels[hive.durum];
  status.style.setProperty("--status", colors[hive.durum]);
  document.querySelector("#detail-summary").innerHTML = `
    <article><span>Güncel durum</span><strong style="color:${colors[hive.durum]}">${labels[hive.durum]}</strong></article>
    <article><span>Model güveni</span><strong>${hive.confidence == null ? "—" : Math.round(hive.confidence * 100) + "%"}</strong></article>
    <article><span>Son sinyal</span><strong>${dateLabel(hive.timestamp)}</strong></article>`;
  document.querySelector("#chart-legend").innerHTML = `<span style="--dot:${hiveColor(hive.hive_id)}">${hiveLabel(hive.hive_id)}</span>`;
  renderChart(latestEvents);
  renderEvents();
}

function showView(viewName) {
  document.querySelectorAll(".app-view").forEach(view => { view.hidden = view.id !== `${viewName}-view`; });
  document.querySelectorAll(".nav-button").forEach(button => button.classList.toggle("active", button.dataset.view === viewName));
  window.scrollTo({top: 0, behavior: "smooth"});
}

function openHiveDetail(hiveId) {
  selectedHiveId = hiveId;
  showView("detail");
  renderHiveDetail();
}

function renderManagedHives() {
  managedHives.innerHTML = latestHives.length ? latestHives.map(hive => `
    <article class="managed-hive-row">
      <div><strong>${escapeHtml(hive.name)}</strong><span>${hive.location ? escapeHtml(hive.location) : "Konum belirtilmedi"}</span></div>
      <code>${hive.hive_id}</code>
    </article>`).join("") : '<p>Henüz kovan eklenmedi.</p>';
}

async function createHive(event) {
  event.preventDefault();
  const message = document.querySelector("#hive-form-message");
  const submit = hiveForm.querySelector('[type="submit"]');
  submit.disabled = true;
  message.textContent = "";
  try {
    const response = await fetch("/api/hives", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name: hiveForm.name.value.trim(), location: hiveForm.location.value.trim() || null}),
    });
    if (!response.ok) throw new Error("Kovan kaydedilemedi");
    const hive = await response.json();
    message.textContent = `${hive.name} ${hive.hive_id} kimliğiyle eklendi.`;
    hiveForm.reset();
    await refresh();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function startDemo() {
  demoButton.disabled = true;
  demoButton.textContent = "Demo hazırlanıyor…";
  try {
    const response = await fetch("/api/demo", { method: "POST" });
    if (!response.ok) throw new Error("Demo başlatılamadı");
    await refresh();
  } finally {
    demoButton.disabled = false;
    demoButton.textContent = "Demo senaryosunu başlat";
  }
}

function renderWeather(weather) {
  document.querySelector("#weather-location").textContent = weather.location;
  document.querySelector("#weather-temp").textContent = `${Math.round(weather.temperature_c)}°`;
  document.querySelector("#weather-details").innerHTML = `<span>Nem %${weather.humidity_percent}</span><span>Rüzgâr ${Math.round(weather.wind_kmh)} km/sa</span>`;
}

function renderReports(reports) {
  latestReports = reports;
  reportSelect.innerHTML = reports.length ? reports.map((report, index) => `<option value="${report.id}">${index === 0 ? "Son rapor" : dateLabel(report.period_end)}</option>`).join("") : '<option value="">Rapor yok</option>';
  renderSelectedReport();
}

function renderSelectedReport() {
  const report = latestReports.find(item => String(item.id) === reportSelect.value) || latestReports[0];
  if (!report) return;
  document.querySelector("#report-period").textContent = `${dateLabel(report.period_start)} – ${dateLabel(report.period_end)}`;
  document.querySelector("#report-summary").textContent = explainHiveIds(report.summary);
  document.querySelector("#report-actions").innerHTML = report.recommendations.map(item => `<li>${escapeHtml(explainHiveIds(item))}</li>`).join("");
}

async function acknowledgeEvent(eventId) {
  const response = await fetch(`/api/events/${eventId}/acknowledge`, { method: "POST" });
  if (!response.ok) throw new Error("Alarm onaylanamadı");
  await refresh();
}

async function refresh() {
  try {
    const dashboardResponse = await fetch("/api/dashboard");
    if (!dashboardResponse.ok) throw new Error("API yanıt vermedi");
    render(await dashboardResponse.json());
  } catch (error) {
    updatedEl.textContent = "Bağlantı kurulamadı";
  }
}

async function refreshContext() {
  const [weatherResponse, reportsResponse] = await Promise.all([
    fetch("/api/weather"), fetch("/api/reports?limit=10")
  ]);
  if (weatherResponse.ok) renderWeather(await weatherResponse.json());
  if (reportsResponse.ok) renderReports(await reportsResponse.json());
}

soundButton.addEventListener("click", () => {
  soundEnabled = !soundEnabled;
  soundButton.textContent = `Sesli alarm: ${soundEnabled ? "açık" : "kapalı"}`;
});
demoButton.addEventListener("click", startDemo);
eventFilter.addEventListener("change", renderEvents);
reportSelect.addEventListener("change", renderSelectedReport);
eventsEl.addEventListener("click", event => {
  const button = event.target.closest("[data-ack]");
  if (button) acknowledgeEvent(button.dataset.ack);
});
hivesEl.addEventListener("click", event => {
  const button = event.target.closest("[data-hive-detail]");
  if (button) openHiveDetail(button.dataset.hiveDetail);
});
document.querySelector("#back-overview").addEventListener("click", () => {
  selectedHiveId = null;
  showView("overview");
});
document.querySelectorAll(".nav-button").forEach(button => button.addEventListener("click", () => {
  selectedHiveId = null;
  showView(button.dataset.view);
}));
document.querySelector("#show-hive-form").addEventListener("click", () => {
  hiveForm.hidden = false;
  document.querySelector("#hive-name").focus();
});
document.querySelector("#cancel-hive-form").addEventListener("click", () => {
  hiveForm.hidden = true;
  hiveForm.reset();
  document.querySelector("#hive-form-message").textContent = "";
});
hiveForm.addEventListener("submit", createHive);
refresh(); refreshContext();
setInterval(refresh, 2500);
setInterval(refreshContext, 300000);
const logoutButton = document.querySelector("#logout-button");
const currentUser = document.querySelector("#current-user");

fetch("/api/me").then((response) => response.json()).then((user) => {
  currentUser.textContent = user.username;
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", {method: "POST"});
  window.location.replace("/login");
});
