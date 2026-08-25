const hivesEl = document.querySelector("#hives");
const eventsEl = document.querySelector("#events");
const updatedEl = document.querySelector("#updated");
const alertEl = document.querySelector("#alert");
const soundButton = document.querySelector("#sound-toggle");
const demoButton = document.querySelector("#demo-button");
const hiveFilter = document.querySelector("#hive-filter");
const eventFilter = document.querySelector("#event-filter");
let soundEnabled = true;
let lastCriticalId = null;
let latestEvents = [];

const labels = { normal: "Normal", uyari: "Uyarı", kritik: "Kritik", veri_yok: "Veri yok" };
const colors = { normal: "#15803d", uyari: "#b7791f", kritik: "#c62828", veri_yok: "#6d7685" };

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
  hivesEl.innerHTML = data.hives.map(hive => `
    <article class="hive-card" style="--status:${colors[hive.durum]}">
      <div class="hive-head"><span class="hive-name">${hive.hive_id}</span><span class="badge">${labels[hive.durum]}</span></div>
      <div class="confidence">${hive.confidence == null ? "—" : Math.round(hive.confidence * 100) + "%"}</div>
      <div class="confidence-label">model güveni</div>
      <div class="event-time">${dateLabel(hive.timestamp)}</div>
    </article>`).join("");

  renderEvents();
  renderChart(data.events);
  updatedEl.textContent = `Son güncelleme ${dateLabel(data.generated_at)}`;

  const critical = data.events.find(event => event.event === "queenless_suspected" && event.confidence >= .85);
  if (critical && critical.id !== lastCriticalId) {
    lastCriticalId = critical.id;
    alertEl.textContent = `${critical.hive_id}: Ana arı kaybı şüphesi (${Math.round(critical.confidence * 100)}%)`;
    alertEl.classList.add("show"); beep();
    setTimeout(() => alertEl.classList.remove("show"), 5500);
  }
}

function renderEvents() {
  const filtered = latestEvents.filter(event =>
    (hiveFilter.value === "all" || event.hive_id === hiveFilter.value) &&
    (eventFilter.value === "all" || event.event === eventFilter.value)
  );
  eventsEl.innerHTML = filtered.length ? filtered.map(event => `
    <tr><td>${dateLabel(event.timestamp)}</td><td>${event.hive_id}</td>
    <td class="${event.event === "queenless_suspected" ? "event-critical" : ""}">${event.event === "queenless_suspected" ? "Ana arı kaybı şüphesi" : event.event === "uncertain" ? "Belirsiz" : "Normal"}</td>
    <td>${Math.round(event.confidence * 100)}%</td></tr>`).join("") : '<tr><td colspan="4">Henüz olay yok.</td></tr>';
}

function renderChart(events) {
  const svg = document.querySelector("#confidence-chart");
  const colors = { H1: "#15803d", H2: "#b7791f", H3: "#c62828" };
  const grid = [0, 25, 50, 75, 100].map(value => {
    const y = 195 - value * 1.7;
    return `<line class="grid-line" x1="45" y1="${y}" x2="885" y2="${y}"/><text class="axis-label" x="5" y="${y + 4}">%${value}</text>`;
  }).join("");
  const series = Object.keys(colors).map(hiveId => {
    const values = events.filter(event => event.hive_id === hiveId).slice(0, 12).reverse();
    if (!values.length) return "";
    const points = values.map((event, index) => {
      const x = values.length === 1 ? 465 : 55 + index * (820 / (values.length - 1));
      return { x, y: 195 - event.confidence * 170 };
    });
    return `<polyline class="chart-line" stroke="${colors[hiveId]}" points="${points.map(point => `${point.x},${point.y}`).join(" ")}"/>${points.map(point => `<circle class="chart-point" fill="${colors[hiveId]}" cx="${point.x}" cy="${point.y}" r="6"/>`).join("")}`;
  }).join("");
  svg.innerHTML = grid + (series || '<text class="chart-empty" x="450" y="110">Grafik için olay bekleniyor</text>');
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
  if (!reports.length) return;
  const report = reports[0];
  document.querySelector("#report-period").textContent = `${dateLabel(report.period_start)} – ${dateLabel(report.period_end)}`;
  document.querySelector("#report-summary").textContent = report.summary;
  document.querySelector("#report-actions").innerHTML = report.recommendations.map(item => `<li>${escapeHtml(item)}</li>`).join("");
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
    fetch("/api/weather"), fetch("/api/reports?limit=1")
  ]);
  if (weatherResponse.ok) renderWeather(await weatherResponse.json());
  if (reportsResponse.ok) renderReports(await reportsResponse.json());
}

soundButton.addEventListener("click", () => {
  soundEnabled = !soundEnabled;
  soundButton.textContent = `Sesli alarm: ${soundEnabled ? "açık" : "kapalı"}`;
});
demoButton.addEventListener("click", startDemo);
hiveFilter.addEventListener("change", renderEvents);
eventFilter.addEventListener("change", renderEvents);
refresh(); refreshContext();
setInterval(refresh, 2500);
setInterval(refreshContext, 300000);
