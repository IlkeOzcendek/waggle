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
const alarmsList = document.querySelector("#alarms-list");
const alarmFilter = document.querySelector("#alarm-filter");
let soundEnabled = true;
let alarmThreshold = .85;
let refreshSeconds = 5;
let refreshTimer = null;
let currentSettings = null;
let lastCriticalId = null;
let latestEvents = [];
let latestReports = [];
let latestHives = [];
let managedHivesData = [];
let alarmEvents = [];
let selectedHiveId = null;
let editingHiveId = null;

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

async function restoreBackup() {
  const input = document.querySelector("#restore-file");
  const message = document.querySelector("#restore-message");
  const button = document.querySelector("#restore-backup");
  const file = input.files[0];
  if (!file) {
    message.textContent = "Önce bir Waggle .db yedek dosyası seçin.";
    return;
  }
  const confirmed = window.confirm(
    "Bu işlem mevcut kovan, olay, alarm, rapor ve ayarları seçilen yedekle değiştirecek. Devam edilsin mi?"
  );
  if (!confirmed) return;
  button.disabled = true;
  message.textContent = "Yedek doğrulanıyor ve geri yükleniyor…";
  try {
    const response = await fetch("/api/backup/restore", {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Waggle-Confirm-Restore": "RESTORE",
      },
      body: await file.arrayBuffer(),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "Yedek geri yüklenemedi");
    message.textContent = `${body.message}. Kurtarma kopyası: ${body.recovery_backup}`;
    input.value = "";
    await Promise.all([refresh(), refreshContext(), refreshManagedHives(), refreshAlarms()]);
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
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
  updatedEl.textContent = `Son güncelleme ${dateLabel(data.generated_at)}`;

  const critical = data.events.find(event => event.event === "queenless_suspected" && event.confidence >= alarmThreshold);
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
  if (viewName === "hives") refreshManagedHives();
  if (viewName === "alarms") refreshAlarms();
  if (viewName === "status") refreshSystemStatus();
  if (viewName === "settings") loadSettings();
}

function applySettings(settings) {
  currentSettings = settings;
  soundEnabled = settings.sound_enabled;
  alarmThreshold = settings.alarm_threshold;
  refreshSeconds = settings.refresh_seconds;
  soundButton.textContent = `Sesli alarm: ${soundEnabled ? "açık" : "kapalı"}`;
  document.querySelector("#panel-name").textContent = settings.panel_name;
  document.title = `${settings.panel_name} | Kovan İzleme`;
  document.querySelector("#settings-panel-name").value = settings.panel_name;
  document.querySelector("#settings-location").value = settings.location_name;
  document.querySelector("#settings-threshold").value = Math.round(settings.alarm_threshold * 100);
  document.querySelector("#threshold-value").textContent = `%${Math.round(settings.alarm_threshold * 100)}`;
  document.querySelector("#settings-sound").checked = settings.sound_enabled;
  document.querySelector("#settings-weather").checked = settings.weather_enabled;
  document.querySelector("#settings-refresh").value = String(settings.refresh_seconds);
  clearInterval(refreshTimer);
  refreshTimer = setInterval(refresh, refreshSeconds * 1000);
}

async function loadSettings(showGuide = false) {
  const response = await fetch("/api/settings");
  if (!response.ok) return;
  const settings = await response.json();
  applySettings(settings);
  if (showGuide && !settings.onboarding_completed) openGuide();
}

function openGuide() {
  const dialog = document.querySelector("#onboarding-dialog");
  if (!dialog.open) dialog.showModal();
}

function closeGuide() {
  document.querySelector("#onboarding-dialog").close();
}

async function completeGuide() {
  if (!currentSettings) return;
  const response = await fetch("/api/settings", {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({...currentSettings, onboarding_completed: true}),
  });
  if (response.ok) applySettings(await response.json());
  closeGuide();
}

async function saveSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('[type="submit"]');
  const message = document.querySelector("#settings-message");
  button.disabled = true;
  message.textContent = "";
  try {
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        panel_name: form.panel_name.value.trim(),
        location_name: form.location_name.value.trim(),
        alarm_threshold: Number(form.alarm_threshold.value) / 100,
        sound_enabled: form.sound_enabled.checked,
        refresh_seconds: Number(form.refresh_seconds.value),
        onboarding_completed: currentSettings?.onboarding_completed || false,
        weather_enabled: form.weather_enabled.checked,
      }),
    });
    if (!response.ok) throw new Error("Ayarlar kaydedilemedi");
    applySettings(await response.json());
    message.textContent = "Ayarlar kaydedildi ve hemen uygulanmaya başladı.";
    await Promise.all([refresh(), refreshContext()]);
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderSystemStatus(data) {
  const overview = document.querySelector("#status-overview");
  overview.className = `status-overview ${data.overall}`;
  overview.innerHTML = `<span class="status-pulse"></span><div><strong>${data.overall === "ok" ? "Tüm sistemler çalışıyor" : "Sistem çalışıyor, bazı bağlantılar veri bekliyor"}</strong><p>${data.overall === "ok" ? "Panel ve bütün entegrasyonlar güncel veri üretiyor." : "Bekleyen bileşenlerin ayrıntılarını aşağıda görebilirsiniz."}</p></div>`;
  const statusLabels = {ok: "Çalışıyor", waiting: "Veri bekleniyor", warning: "Kontrol gerekli"};
  document.querySelector("#status-components").innerHTML = data.components.map(component => `
    <article class="status-card ${component.status}">
      <span class="component-dot" aria-hidden="true"></span>
      <div><div class="status-card-title"><h3>${escapeHtml(component.name)}</h3><span>${statusLabels[component.status]}</span></div><strong>${escapeHtml(component.summary)}</strong><p>${escapeHtml(component.detail)}</p>${component.last_seen_at ? `<small>Son bağlantı: ${dateLabel(component.last_seen_at)}</small>` : ""}</div>
    </article>`).join("");
  document.querySelector("#status-updated").textContent = `Son kontrol: ${dateLabel(data.generated_at)}`;
  const header = document.querySelector(".connection");
  header.classList.toggle("attention", data.overall !== "ok");
  header.lastChild.textContent = data.overall === "ok" ? " Sistem bağlı" : " Sistem çalışıyor";
}

async function refreshSystemStatus() {
  const button = document.querySelector("#refresh-status");
  button.disabled = true;
  try {
    const response = await fetch("/api/system-status");
    if (!response.ok) throw new Error("Sistem durumu alınamadı");
    renderSystemStatus(await response.json());
  } catch (error) {
    document.querySelector("#status-overview").innerHTML = `<span class="status-pulse"></span><div><strong>Durum alınamadı</strong><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    button.disabled = false;
  }
}

function openHiveDetail(hiveId) {
  selectedHiveId = hiveId;
  showView("detail");
  renderHiveDetail();
}

function renderManagedHives() {
  managedHives.innerHTML = managedHivesData.length ? managedHivesData.map(hive => `
    <article class="managed-hive-row ${hive.active ? "" : "archived"}">
      <div><strong>${escapeHtml(hive.name)}</strong><span>${hive.location ? escapeHtml(hive.location) : "Konum belirtilmedi"}</span></div>
      <div class="managed-hive-actions">
        <code>${hive.hive_id}</code>
        ${hive.active ? `<button data-edit-hive="${hive.hive_id}" type="button">Düzenle</button><button class="archive-button" data-archive-hive="${hive.hive_id}" type="button">Pasif hâle getir</button>` : `<span class="archived-label">Arşivlendi</span><button data-restore-hive="${hive.hive_id}" type="button">Yeniden etkinleştir</button>`}
      </div>
    </article>`).join("") : '<p>Henüz kovan eklenmedi.</p>';
}

async function saveHive(event) {
  event.preventDefault();
  const message = document.querySelector("#hive-form-message");
  const submit = hiveForm.querySelector('[type="submit"]');
  submit.disabled = true;
  message.textContent = "";
  try {
    const response = await fetch(editingHiveId ? `/api/hives/${editingHiveId}` : "/api/hives", {
      method: editingHiveId ? "PUT" : "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name: hiveForm.name.value.trim(), location: hiveForm.location.value.trim() || null}),
    });
    if (!response.ok) throw new Error("Kovan kaydedilemedi");
    const hive = await response.json();
    const successMessage = editingHiveId ? `${hive.name} güncellendi.` : `${hive.name} ${hive.hive_id} kimliğiyle eklendi.`;
    editingHiveId = null;
    hiveForm.reset();
    document.querySelector("#hive-form-title").textContent = "Yeni kovan ekle";
    document.querySelector("#save-hive-button").textContent = "Kovanı kaydet";
    message.textContent = successMessage;
    await refresh();
    await refreshManagedHives();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function refreshManagedHives() {
  const response = await fetch("/api/hives?include_inactive=true");
  if (!response.ok) return;
  managedHivesData = await response.json();
  renderManagedHives();
}

function openEditHive(hiveId) {
  const hive = managedHivesData.find(item => item.hive_id === hiveId);
  if (!hive) return;
  editingHiveId = hiveId;
  hiveForm.hidden = false;
  hiveForm.name.value = hive.name;
  hiveForm.location.value = hive.location || "";
  document.querySelector("#hive-form-title").textContent = `${hive.name} bilgilerini düzenle`;
  document.querySelector("#save-hive-button").textContent = "Değişiklikleri kaydet";
  document.querySelector("#hive-name").focus();
}

async function setHiveActive(hiveId, active) {
  const action = active ? "restore" : "archive";
  const response = await fetch(`/api/hives/${hiveId}/${action}`, {method: "POST"});
  if (!response.ok) throw new Error("Kovan durumu değiştirilemedi");
  await refresh();
  await refreshManagedHives();
}

function resetHiveForm() {
  editingHiveId = null;
  hiveForm.hidden = true;
  hiveForm.reset();
  document.querySelector("#hive-form-title").textContent = "Yeni kovan ekle";
  document.querySelector("#save-hive-button").textContent = "Kovanı kaydet";
  document.querySelector("#hive-form-message").textContent = "";
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

function renderWeatherDisabled() {
  document.querySelector("#weather-location").textContent = "Çevrimiçi hava durumu kapalı";
  document.querySelector("#weather-temp").textContent = "—";
  document.querySelector("#weather-details").innerHTML = "<span>Temel kovan izleme internet olmadan çalışmaya devam eder.</span>";
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
  await refreshAlarms();
}

function renderAlarms() {
  const criticalEvents = alarmEvents.filter(event => event.event === "queenless_suspected");
  const openEvents = criticalEvents.filter(event => !event.acknowledged_at);
  const navCount = document.querySelector("#nav-alarm-count");
  navCount.textContent = openEvents.length;
  navCount.hidden = openEvents.length === 0;
  document.querySelector("#open-alarm-count").textContent = openEvents.length;
  const filtered = criticalEvents.filter(event =>
    alarmFilter.value === "all" ||
    (alarmFilter.value === "open" && !event.acknowledged_at) ||
    (alarmFilter.value === "acknowledged" && event.acknowledged_at)
  );
  alarmsList.innerHTML = filtered.length ? filtered.map(event => `
    <article class="alarm-card ${event.acknowledged_at ? "resolved" : "open"}">
      <div class="alarm-icon" aria-hidden="true">${event.acknowledged_at ? "✓" : "!"}</div>
      <div class="alarm-content">
        <div class="alarm-card-head"><div><strong>${escapeHtml(hiveLabel(event.hive_id))}</strong><span>${dateLabel(event.timestamp)}</span></div><span class="alarm-confidence">%${Math.round(event.confidence * 100)} güven</span></div>
        <h3>Ana arı kaybı şüphesi</h3>
        <p>${event.acknowledged_at ? `Kontrol edildi: ${dateLabel(event.acknowledged_at)}` : "Kovanın fiziksel olarak kontrol edilmesi öneriliyor."}</p>
      </div>
      ${event.acknowledged_at ? '<span class="resolved-label">Kontrol edildi</span>' : `<button class="ack-button alarm-ack-button" data-alarm-ack="${event.id}" type="button">Kontrol edildi olarak işaretle</button>`}
    </article>`).join("") : `<div class="empty-state"><strong>${alarmFilter.value === "open" ? "Açık alarm yok" : "Bu filtrede alarm yok"}</strong><p>Kovanlarınızın kritik olayları burada görünecek.</p></div>`;
}

async function refreshAlarms() {
  const [eventsResponse, hivesResponse] = await Promise.all([
    fetch("/api/events?limit=200"),
    fetch("/api/hives?include_inactive=true"),
  ]);
  if (hivesResponse.ok) {
    const hives = await hivesResponse.json();
    hives.forEach(hive => { hiveNames[hive.hive_id] = hive.name; });
  }
  if (eventsResponse.ok) {
    alarmEvents = await eventsResponse.json();
    renderAlarms();
  }
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
  const weatherRequest = currentSettings?.weather_enabled ? fetch("/api/weather") : null;
  const [weatherResponse, reportsResponse] = await Promise.all([
    weatherRequest, fetch("/api/reports?limit=10")
  ]);
  if (weatherResponse?.ok) renderWeather(await weatherResponse.json());
  else if (!currentSettings?.weather_enabled) renderWeatherDisabled();
  if (reportsResponse.ok) renderReports(await reportsResponse.json());
}

soundButton.addEventListener("click", () => {
  soundEnabled = !soundEnabled;
  soundButton.textContent = `Sesli alarm: ${soundEnabled ? "açık" : "kapalı"}`;
});
demoButton.addEventListener("click", startDemo);
eventFilter.addEventListener("change", renderEvents);
alarmFilter.addEventListener("change", renderAlarms);
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
  resetHiveForm();
  hiveForm.hidden = false;
  document.querySelector("#hive-name").focus();
});
document.querySelector("#cancel-hive-form").addEventListener("click", () => {
  resetHiveForm();
});
hiveForm.addEventListener("submit", saveHive);
managedHives.addEventListener("click", event => {
  const editButton = event.target.closest("[data-edit-hive]");
  const archiveButton = event.target.closest("[data-archive-hive]");
  const restoreButton = event.target.closest("[data-restore-hive]");
  if (editButton) openEditHive(editButton.dataset.editHive);
  if (archiveButton) setHiveActive(archiveButton.dataset.archiveHive, false);
  if (restoreButton) setHiveActive(restoreButton.dataset.restoreHive, true);
});
alarmsList.addEventListener("click", event => {
  const button = event.target.closest("[data-alarm-ack]");
  if (button) acknowledgeEvent(button.dataset.alarmAck);
});
document.querySelector("#refresh-status").addEventListener("click", refreshSystemStatus);
document.querySelector("#restore-backup").addEventListener("click", restoreBackup);
document.querySelector("#settings-threshold").addEventListener("input", event => {
  document.querySelector("#threshold-value").textContent = `%${event.target.value}`;
});
document.querySelector("#settings-form").addEventListener("submit", saveSettings);
document.querySelector("#reopen-guide").addEventListener("click", openGuide);
document.querySelector("#close-guide").addEventListener("click", closeGuide);
document.querySelector("#complete-guide").addEventListener("click", completeGuide);
loadSettings(true).finally(() => {
  if (!refreshTimer) refreshTimer = setInterval(refresh, refreshSeconds * 1000);
  refresh(); refreshContext(); refreshAlarms();
});
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
