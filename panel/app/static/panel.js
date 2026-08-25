const hivesEl = document.querySelector("#hives");
const eventsEl = document.querySelector("#events");
const updatedEl = document.querySelector("#updated");
const alertEl = document.querySelector("#alert");
const soundButton = document.querySelector("#sound-toggle");
let soundEnabled = true;
let lastCriticalId = null;

const labels = { normal: "Normal", uyari: "Uyarı", kritik: "Kritik", veri_yok: "Veri yok" };
const colors = { normal: "#15803d", uyari: "#b7791f", kritik: "#c62828", veri_yok: "#6d7685" };

function dateLabel(value) {
  if (!value) return "Henüz sinyal yok";
  return new Intl.DateTimeFormat("tr-TR", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
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
  hivesEl.innerHTML = data.hives.map(hive => `
    <article class="hive-card" style="--status:${colors[hive.durum]}">
      <div class="hive-head"><span class="hive-name">${hive.hive_id}</span><span class="badge">${labels[hive.durum]}</span></div>
      <div class="confidence">${hive.confidence == null ? "—" : Math.round(hive.confidence * 100) + "%"}</div>
      <div class="confidence-label">model güveni</div>
      <div class="event-time">${dateLabel(hive.timestamp)}</div>
    </article>`).join("");

  eventsEl.innerHTML = data.events.length ? data.events.map(event => `
    <tr><td>${dateLabel(event.timestamp)}</td><td>${event.hive_id}</td>
    <td class="${event.event === "queenless_suspected" ? "event-critical" : ""}">${event.event === "queenless_suspected" ? "Ana arı kaybı şüphesi" : event.event === "uncertain" ? "Belirsiz" : "Normal"}</td>
    <td>${Math.round(event.confidence * 100)}%</td></tr>`).join("") : '<tr><td colspan="4">Henüz olay yok.</td></tr>';
  updatedEl.textContent = `Son güncelleme ${dateLabel(data.generated_at)}`;

  const critical = data.events.find(event => event.event === "queenless_suspected" && event.confidence >= .85);
  if (critical && critical.id !== lastCriticalId) {
    lastCriticalId = critical.id;
    alertEl.textContent = `${critical.hive_id}: Ana arı kaybı şüphesi (${Math.round(critical.confidence * 100)}%)`;
    alertEl.classList.add("show"); beep();
    setTimeout(() => alertEl.classList.remove("show"), 5500);
  }
}

async function refresh() {
  try {
    const response = await fetch("/api/dashboard");
    if (!response.ok) throw new Error("API yanıt vermedi");
    render(await response.json());
  } catch (error) {
    updatedEl.textContent = "Bağlantı kurulamadı";
  }
}

soundButton.addEventListener("click", () => {
  soundEnabled = !soundEnabled;
  soundButton.textContent = `Sesli alarm: ${soundEnabled ? "açık" : "kapalı"}`;
});
refresh(); setInterval(refresh, 2500);
