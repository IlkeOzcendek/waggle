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
const sensorDevice = document.querySelector("#sensor-device");
const sensorAudio = document.querySelector("#sensor-audio");
const sensorButton = document.querySelector("#analyze-sensor-audio");
const sensorMessage = document.querySelector("#sensor-message");
const sensorResult = document.querySelector("#sensor-result");
let soundEnabled = true;
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
let currentLanguage = "tr";
let managedHiveId = null;
let managedDevices = [];
let managedEnrollment = null;

const english = {
  "Ana içeriğe geç": "Skip to main content",
  "EDGE AI KOVAN İZLEME": "EDGE AI HIVE MONITORING",
  "Kovanları dinleyen yapay zekâ": "AI that listens to hives",
  "Sistem bağlı": "System connected",
  "Sistem çalışıyor": "System running",
  "Dili değiştir": "Change language", "Ana menü": "Main navigation",
  "Çıkış yap": "Sign out",
  "Genel Bakış": "Overview", "Kovanlarım": "My hives", "Alarmlar": "Alarms",
  "Raporlar": "Reports", "Telefon Sensörü": "Phone Sensor", "Dışa Aktar": "Export", "Sistem Durumu": "System status", "Ayarlar": "Settings",
  "GENEL BAKIŞ": "OVERVIEW", "Kovanlarınızın durumu": "Status of your hives",
  "Veri bekleniyor…": "Waiting for data…", "Demo senaryosunu başlat": "Start demo scenario",
  "Toplam kovan": "Total hives", "Normal": "Normal", "Uyarı": "Watch", "Kritik": "Critical", "Veri yok": "No data",
  "Detaylarını görmek istediğiniz kovanı seçin.": "Select a hive to view its details.",
  "SAHA BAĞLAMI": "FIELD CONTEXT", "Hava durumu": "Weather", "Yükleniyor…": "Loading…",
  "← Tüm kovanlara dön": "← Back to all hives", "KOVAN DETAYI": "HIVE DETAIL", "Kovan": "Hive",
  "Veri bekleniyor": "Waiting for data", "EĞİLİM": "TREND", "Akustik değişim oranı": "Acoustic change ratio",
  "TELEMETRİ": "TELEMETRY", "Son olaylar": "Recent events", "Durum": "Status", "Tümü": "All",
  "İzle": "Watch", "Alarm": "Alarm", "Sesli alarm: açık": "Audible alarm: on", "Sesli alarm: kapalı": "Audible alarm: off",
  "Zaman": "Time", "Aykırı ses": "Anomalous audio", "İşlem": "Action", "Henüz olay yok.": "No events yet.",
  "YAPAY ZEKÂ RAPORU": "AI REPORT", "Haftalık değerlendirmeler": "Weekly assessments",
  "Rapor geçmişi": "Report history", "Rapor yok": "No reports", "Son rapor": "Latest report",
  "Türkçe rapor": "Turkish report", "İngilizce rapor": "English report", "Üretici": "Generator",
  "Henüz rapor üretilmedi. Foundry Local veya sahte rapor üreticisi bu alanı besleyecek.": "No report has been generated yet. Foundry Local will populate this area.",
  "KOVAN YÖNETİMİ": "HIVE MANAGEMENT", "+ Yeni kovan ekle": "+ Add new hive",
  "Yeni kovan ekle": "Add new hive", "Kovan adı": "Hive name", "Konum": "Location", "Vazgeç": "Cancel", "Kovanı kaydet": "Save hive",
  "Örn. Arka Bahçe Kovanı": "E.g. Backyard Hive", "Örn. Ankara / Gölbaşı": "E.g. Ankara / Gölbaşı",
  "ALARM MERKEZİ": "ALARM CENTER", "Kritik olaylar": "Critical events", "Göster": "Show",
  "Açık alarmlar": "Open alarms", "Kontrol edilenler": "Inspected", "Açık alarm": "Open alarms",
  "Açık alarmları fiziksel kovan kontrolünden sonra işaretleyin.": "Mark alarms only after a physical hive inspection.",
  "Alarm verileri yükleniyor…": "Loading alarm data…", "Kalıcı akustik değişim": "Persistent acoustic change",
  "Kontrol edildi": "Inspected", "Kontrol edildi olarak işaretle": "Mark as inspected",
  "VERİ YÖNETİMİ": "DATA MANAGEMENT", "Dışa aktar": "Export", "CSV indir": "Download CSV", "JSON indir": "Download JSON",
  "Tüm olaylar": "All events", "Kritik alarmlar": "Critical alarms", "Tam veritabanı yedeği": "Full database backup",
  "SQLite yedeğini indir": "Download SQLite backup", "Yedekten geri yükle": "Restore backup", "Yedek dosyası": "Backup file",
  "BAĞLANTI VE ENTEGRASYON": "CONNECTIVITY AND INTEGRATION", "Sistem durumu": "System status", "Şimdi kontrol et": "Check now",
  "Kontrol ediliyor…": "Checking…", "Sistem bileşenleri sorgulanıyor.": "Checking system components.",
  "KİŞİSELLEŞTİRME": "PERSONALIZATION", "Panel bilgileri": "Panel information", "Panel adı": "Panel name",
  "Kovanlık konumu": "Apiary location", "Alarm davranışı": "Alarm behavior", "Sesli alarm": "Audible alarm",
  "Ekran yenileme": "Screen refresh", "Yenileme sıklığı": "Refresh interval", "Uygulama dili": "Application language",
  "Panel ve yapay zekâ raporlarının dilini seçin.": "Choose the language of the panel and AI reports.", "Dil": "Language", "Türkçe": "Turkish",
  "İsteğe bağlı çevrimiçi özellikler": "Optional online features", "Çevrimiçi hava durumu": "Online weather",
  "Yardım ve başlangıç rehberi": "Help and getting-started guide", "Başlangıç rehberini aç": "Open getting-started guide",
  "Ayarları kaydet": "Save settings", "HIZLI BAŞLANGIÇ": "QUICK START", "Waggle’a hoş geldiniz": "Welcome to Waggle",
  "Anladım, panele geç": "Got it, open the panel"
  ,"İzleme kaynağını bağlayın": "Connect a monitoring source"
  ,"Kovan cihazından veya akustik analiz servisinden gelen olaylar güvenli biçimde panele aktarılır. Bağlantı durumunu": "Events from the hive device or acoustic analysis service are securely delivered to the panel. You can track the connection status in the"
  ,"ekranından takip edebilirsiniz.": "screen."
  ,"Bahçe Kovanı": "Garden Hive", "Orman Kovanı": "Forest Hive", "Deneme Kovanı": "Demo Hive"
  ,"Test alanı": "Test site", "aykırı ses penceresi": "anomalous audio windows", "Detayları gör": "View details"
  ,"Son güncelleme": "Last updated", "Kovanın fiziksel olarak kontrol edilmesi öneriliyor.": "A physical hive inspection is recommended."
  ,"aykırı ses": "anomalous audio", "Açık alarm yok": "No open alarms", "Bu filtrede alarm yok": "No alarms match this filter"
  ,"Kovanlarınızın kritik olayları burada görünecek.": "Critical hive events will appear here."
  ,"Tüm sistemler çalışıyor": "All systems operational", "Sistem çalışıyor, bazı bağlantılar veri bekliyor": "System operational; some integrations are waiting for data"
  ,"Panel ve bütün entegrasyonlar güncel veri üretiyor.": "The panel and all integrations are producing current data."
  ,"Bekleyen bileşenlerin ayrıntılarını aşağıda görebilirsiniz.": "Details of pending components are shown below."
  ,"Çalışıyor": "Operational", "Kontrol gerekli": "Check required", "Son bağlantı": "Last connection", "Son kontrol": "Last checked"
  ,"Canlı veri alınıyor": "Receiving live data", "Cihaz veya model sonuçları güvenli bağlantı üzerinden panele ulaşıyor.": "Device or model results are reaching the panel over a secure connection."
  ,"İlk veri bekleniyor": "Waiting for first event", "Kovan cihazı veya akustik analiz servisi ilk olayı gönderdiğinde bağlantı zamanı burada görünecek.": "The connection time will appear here after the hive device or acoustic analysis service sends its first event."
  ,"Cihaz verisi gecikiyor": "Device data is delayed", "Son olay beklenen süreden eski. Kovan cihazını, modeli ve yerel ağ bağlantısını kontrol edin.": "The latest event is older than expected. Check the hive device, model, and local network."
  ,"Rapor entegrasyonu çalışıyor": "Report integration operational", "Üretilen değerlendirme raporları panele kaydediliyor.": "Generated assessment reports are being stored in the panel."
  ,"İlk rapor bekleniyor": "Waiting for first report", "İlk haftalık değerlendirme gönderildiğinde burada son rapor zamanı görünecek.": "The latest report time will appear here after the first assessment is submitted."
  ,"Rapor güncel değil": "Report is outdated", "Son haftalık değerlendirme beklenen süreden eski. Rapor üretim akışını kontrol edin.": "The latest assessment is older than expected. Check the report generation flow."
  ,"Grafik için olay bekleniyor": "Waiting for events to plot", "Güncel durum": "Current status", "Son sinyal": "Latest signal", "Aykırı ses penceresi": "Anomalous audio windows"
  ,"Ayarlar kaydedilemedi": "Settings could not be saved", "Ayarlar kaydedildi ve hemen uygulanmaya başladı.": "Settings saved and applied immediately."
  ,"Sistem durumu alınamadı": "System status could not be loaded", "Durum alınamadı": "Status unavailable"
  ,"Konum belirtilmedi": "Location not specified", "Düzenle": "Edit", "Pasif hâle getir": "Deactivate", "Arşivlendi": "Archived", "Yeniden etkinleştir": "Reactivate", "Henüz kovan eklenmedi.": "No hives have been added yet."
  ,"Yeni kovan ekle": "Add new hive", "Kovanı kaydet": "Save hive", "Değişiklikleri kaydet": "Save changes"
  ,"Kovan kaydedilemedi": "Hive could not be saved", "Kovan durumu değiştirilemedi": "Hive status could not be changed"
  ,"Demo hazırlanıyor…": "Preparing demo…", "Demo başlatılamadı": "Demo could not be started"
  ,"Çevrimiçi hava durumu kapalı": "Online weather is disabled", "Temel kovan izleme internet olmadan çalışmaya devam eder.": "Core hive monitoring continues without an internet connection."
  ,"Nem": "Humidity", "Rüzgâr": "Wind", "Kovan İzleme": "Hive Monitoring", "Bağlantı kurulamadı": "Connection failed"
  ,"Önce bir Waggle .db yedek dosyası seçin.": "Select a Waggle .db backup file first."
  ,"Yedek doğrulanıyor ve geri yükleniyor…": "Validating and restoring backup…", "Yedek geri yüklenemedi": "Backup could not be restored"
  ,"Alarm onaylanamadı": "Alarm could not be acknowledged", "API yanıt vermedi": "The API did not respond"
  ,"Bahçe": "Garden", "Orman": "Forest"
  ,"Kovan adlarını ve konumlarını buradan yönetin. Sensör kimliği sistem tarafından otomatik oluşturulur.": "Manage hive names and locations here. The system creates the sensor ID automatically."
  ,"Kayıtları Excel için CSV veya sistem entegrasyonları için JSON biçiminde indirin.": "Download records as CSV for Excel or JSON for system integrations."
  ,"Kovanlar": "Hives", "Aktif ve arşivlenmiş bütün kovanların adları, konumları ve teknik kimlikleri.": "Names, locations, and technical IDs of all active and archived hives."
  ,"Model durumları, akustik değişim oranları, zamanlar ve kovan bilgileri.": "Model states, acoustic change ratios, timestamps, and hive information."
  ,"Açık ve kontrol edilmiş ana arı kaybı şüphesi kayıtları.": "Open and inspected records of suspected queen-loss-compatible acoustic change."
  ,"Haftalık değerlendirmeler, öneriler ve ilgili kovanlar.": "Weekly assessments, recommendations, and related hives."
  ,"Kovanlar, olaylar, alarm durumları ve raporları içeren tutarlı SQLite yedeğini indirin. Bu dosyayı güvenli bir yerde saklayın.": "Download a consistent SQLite backup containing hives, events, alarm states, and reports. Store this file securely."
  ,"Geçerli bir Waggle SQLite yedeği seçin. Mevcut veriler değiştirilmeden hemen önce sunucuda otomatik bir kurtarma kopyası oluşturulur.": "Select a valid Waggle SQLite backup. The server creates a recovery copy immediately before changing existing data."
  ,"Yedeği geri yükle": "Restore backup"
  ,"Panelin, kayıt sisteminin ve yapay zekâ bağlantılarının çalışıp çalışmadığını buradan takip edin.": "Monitor the panel, data store, and AI integrations from here."
  ,"Waggle paneli": "Waggle panel", "Panel çalışıyor": "Panel operational", "Kullanıcı arayüzü ve API istekleri yanıt veriyor.": "The user interface and API are responding."
  ,"Veri kayıt sistemi": "Data store", "Veritabanı sağlam": "Database healthy"
  ,"Kovan cihazları ve yapay zekâ modeli": "Hive devices and acoustic model", "Haftalık yapay zekâ raporları": "AI assessment reports"
  ,"Panel adını, konum bilgisini ve alarm davranışını buradan değiştirebilirsiniz.": "Change the panel name, location, and alarm behavior here."
  ,"Kullanıcıların panelde göreceği ad ve saha konumu.": "The name and field location shown to panel users."
  ,"Alarm eşiği kovana özel akustik model tarafından belirlenir; panel bu kararı değiştirmez.": "The hive-specific acoustic model determines the alarm threshold; the panel does not alter that decision."
  ,"Kritik olay geldiğinde uyarı sesi çal.": "Play an alert sound when a critical event arrives."
  ,"Kovan bilgilerinin kaç saniyede bir güncelleneceğini seçin.": "Choose how often hive information is refreshed."
  ,"2 saniye": "2 seconds", "5 saniye": "5 seconds", "10 saniye": "10 seconds", "30 saniye": "30 seconds", "60 saniye": "60 seconds"
  ,"Waggle’ın temel kovan izleme işlevleri internet olmadan çalışır.": "Waggle's core hive monitoring functions work without internet access."
  ,"Açıldığında yapılandırılmış koordinatlar Open-Meteo servisine gönderilir.": "When enabled, the configured coordinates are sent to Open-Meteo."
  ,"Waggle’ın temel kullanım adımlarını yeniden görüntüleyin.": "Review Waggle's essential usage steps."
  ,"Kovanınızı ekleyin": "Add your hive", "Uyarıları takip edin": "Follow alerts", "Rapor ve yedekleri kullanın": "Use reports and backups"
  ,"Dört kısa adımda kovanlarınızı izlemeye başlayın.": "Start monitoring your hives in four short steps."
  ,"Bu rehberi daha sonra Ayarlar bölümünden tekrar açabilirsiniz.": "You can reopen this guide later from Settings."
  ,"MOBİL SES KAYDI": "MOBILE AUDIO CAPTURE", "Telefonu sensör olarak kullan": "Use this phone as a sensor", "Yerel ağ": "Local network"
  ,"Telefonunuzla kısa bir kovan sesi kaydedin veya mevcut bir ses dosyası seçin. Kayıt tarayıcıda WAV biçimine dönüştürülür, Mac’teki ONNX modeliyle analiz edilir ve sonuç SQLite’a kaydedilir.": "Record a short hive sound with your phone or choose an existing audio file. The browser converts it to WAV, the ONNX model on the Mac analyzes it, and the result is stored in SQLite."
  ,"Kovanı seçin": "Select a hive", "Kovanlar yükleniyor…": "Loading hives…", "Ses kaydedin veya dosya seçin": "Record audio or choose a file"
  ,"10–30 saniyelik kayıt önerilir. Ses yalnızca yerel Waggle sunucusuna gönderilir.": "A 10–30 second recording is recommended. Audio is sent only to the local Waggle server."
  ,"ONNX ile analiz et": "Analyze with ONNX", "Demo profili": "Demo profile"
  ,"Paketlenmiş model referans kovan profilini kullanır. Gerçek saha kullanımında her kovan ve mikrofon için sağlıklı başlangıç profili oluşturulmalıdır.": "The packaged model uses a reference hive profile. Real field use requires a healthy baseline profile for each hive and microphone."
  ,"Önce bir kovan seçin.": "Select a hive first.", "Önce bir ses kaydedin veya dosya seçin.": "Record audio or choose a file first."
  ,"Ses hazırlanıyor…": "Preparing audio…", "ONNX modeli analiz ediyor…": "The ONNX model is analyzing…", "Analiz tamamlandı": "Analysis complete"
  ,"Pencere": "Windows", "Kaynak": "Source", "Yeni olay panele ve SQLite’a kaydedildi.": "The new event was stored in the panel and SQLite."
  ,"Ses dosyası tarayıcı tarafından açılamadı.": "The browser could not open this audio file.", "Ses analizi başarısız oldu": "Audio analysis failed"
  ,"CİHAZ VE MODEL": "DEVICE AND MODEL", "Kovan kurulumu": "Hive setup", "Kapat": "Close", "+ Cihaz ekle": "+ Add device"
  ,"Cihaz adı": "Device name", "Cihaz türü": "Device type", "Kovan telefonu": "Hive phone", "Telefon mikrofonu": "Phone microphone"
  ,"Akustik sensör": "Acoustic sensor", "WAV klasörü": "WAV folder", "Demo cihazı": "Demo device", "Cihazlar ve model": "Devices and model"
  ,"Bağlı cihaz": "Connected device", "Ses kaydı seçin": "Choose an audio recording", "Kaydı gönder": "Send recording"
  ,"iPhone’da Sesli Notlar ile kaydedip dosyayı seçin. Kayıt yalnızca yerel Waggle sunucusuna gönderilir.": "Record with Voice Memos on iPhone, then choose the file. Audio is sent only to the local Waggle server."
  ,"Cihaz bekleniyor": "Waiting for device", "Öğrenme devam ediyor": "Learning in progress", "Profil hazır": "Profile ready", "İzleme etkin": "Monitoring active"
  ,"Sağlıklı başlangıç kaydı": "Healthy baseline recording", "İzleme kaydı": "Monitoring recording"
  ,"Önce bir cihaz ekleyin.": "Add a device first.", "Cihaz eklenemedi": "Device could not be added"
  ,"Cihaz kovana bağlandı. Sağlıklı başlangıç kayıtlarını toplamaya başlayabilirsiniz.": "The device is linked to the hive. You can begin collecting healthy baseline recordings."
  ,"Bu kovanın profili hazır; yeni kayıtlar izleme ve alarm akışında değerlendirilir.": "This hive profile is ready; new recordings are evaluated by the monitoring and alert pipeline."
  ,"Profil hazır olana kadar alarm üretilmez.": "No alerts are generated until the profile is ready.", "kayıt": "recordings", "gün": "days"
  ,"Saha sağlık kontrolü zamanı": "Field health check due", "Bu kısa kontrol en fazla dört günde bir istenir. Emin değilseniz kayıt modele eklenmez.": "This short check is requested at most once every four days. If you are unsure, the recording is not added to the model."
  ,"Gözleminiz": "Your observation", "Kraliçe görüldü": "Queen observed", "Yumurta veya yavru düzeni sağlıklı": "Egg or brood pattern is healthy"
  ,"Kovan genel olarak sağlıklı görünüyor": "Hive appears generally healthy", "Emin değilim": "I am not sure", "Not (isteğe bağlı)": "Note (optional)", "Kontrolü kaydet": "Save check"
  ,"Saha kontrolü kaydedilemedi": "Field check could not be saved", "Saha kontrolü kaydedildi.": "Field check saved."
  ,"Yeni bir saha sağlık doğrulaması gerekiyor": "A new field health confirmation is required.", "saha doğrulaması": "field confirmations"
  ,"Sağlıklı başlangıç kaydı eklendi. Profil hazır olana kadar alarm üretilmez.": "Healthy baseline recording added. No alerts are generated until the profile is ready."
  ,"Kovana özel profil doğrulandı ve izleme etkinleştirildi.": "The hive-specific profile was verified and monitoring is now active."
};

function t(value) { return currentLanguage === "en" ? (english[value] || value) : value; }

function td(value) {
  const translated = t(value);
  if (currentLanguage !== "en" || translated !== value) return translated;
  const counts = value.match(/^(\d+) kovan, (\d+) olay ve (\d+) rapor kayıtlı\.$/);
  if (counts) return `${counts[1]} hives, ${counts[2]} events, and ${counts[3]} reports stored.`;
  return value;
}

function translatePage(root = document.body) {
  document.documentElement.lang = currentLanguage;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node._waggleOriginal) node._waggleOriginal = node.nodeValue;
    const original = node._waggleOriginal;
    const trimmed = original.trim();
    if (!trimmed) continue;
    const translated = t(trimmed);
    node.nodeValue = original.replace(trimmed, translated);
  }
  document.querySelectorAll("[placeholder],[aria-label],[title]").forEach(element => {
    ["placeholder", "aria-label", "title"].forEach(attribute => {
      if (!element.hasAttribute(attribute)) return;
      const dataKey = `waggle${attribute.replace('-', '')}`;
      if (!element.dataset[dataKey]) element.dataset[dataKey] = element.getAttribute(attribute);
      element.setAttribute(attribute, t(element.dataset[dataKey]));
    });
  });
  document.querySelector("#language-toggle").textContent = currentLanguage === "tr" ? "EN" : "TR";
}

function statusLabel(status) { return t({ normal: "Normal", uyari: "Uyarı", kritik: "Kritik", veri_yok: "Veri yok" }[status]); }
const colors = { normal: "#15803d", uyari: "#b7791f", kritik: "#c62828", veri_yok: "#6d7685" };
const hiveNames = { H1: "Bahçe Kovanı", H2: "Orman Kovanı", H3: "Deneme Kovanı" };

function displayHiveName(name) { return t(name); }

function hiveLabel(hiveId) {
  return `${displayHiveName(hiveNames[hiveId]) || t("Kovan")} (${hiveId})`;
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
  if (!value) return currentLanguage === "tr" ? "Henüz sinyal yok" : "No signal yet";
  return new Intl.DateTimeFormat(currentLanguage === "tr" ? "tr-TR" : "en-GB", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
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
    message.textContent = t("Önce bir Waggle .db yedek dosyası seçin.");
    return;
  }
  const confirmed = window.confirm(
    "Bu işlem mevcut kovan, olay, alarm, rapor ve ayarları seçilen yedekle değiştirecek. Devam edilsin mi?"
  );
  if (!confirmed) return;
  button.disabled = true;
  message.textContent = t("Yedek doğrulanıyor ve geri yükleniyor…");
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
    if (!response.ok) throw new Error(body.detail || t("Yedek geri yüklenemedi"));
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
      <div class="hive-head"><span class="hive-name">${escapeHtml(displayHiveName(hive.name))}<small>${hive.hive_id}${hive.location ? ` · ${escapeHtml(t(hive.location))}` : ""}</small></span><span class="badge">${statusLabel(hive.durum)}</span></div>
      <div class="confidence">${hive.anomaly_fraction == null ? "—" : Math.round(hive.anomaly_fraction * 100) + "%"}</div>
      <div class="confidence-label">${t("aykırı ses penceresi")}</div>
      <div class="event-time">${dateLabel(hive.timestamp)}</div>
      <button class="hive-detail-button" data-hive-detail="${hive.hive_id}" type="button">${t("Detayları gör")} <span>→</span></button>
    </article>`).join("");

  if (selectedHiveId) renderHiveDetail();
  updatedEl.textContent = `${t("Son güncelleme")} ${dateLabel(data.generated_at)}`;

  const critical = data.events.find(event => event.status === "ALARM");
  if (critical && critical.id !== lastCriticalId) {
    lastCriticalId = critical.id;
    alertEl.textContent = currentLanguage === "en"
      ? `${hiveLabel(critical.hive_id)}: Persistent acoustic change — inspect the hive and verify the queen's condition`
      : `${hiveLabel(critical.hive_id)}: Kalıcı akustik değişim — kovanı ve kraliçeyi kontrol edin`;
    alertEl.classList.add("show"); beep();
    setTimeout(() => alertEl.classList.remove("show"), 5500);
  }
}

function renderEvents() {
  const filtered = latestEvents.filter(event =>
    (!selectedHiveId || event.hive_id === selectedHiveId) &&
    (eventFilter.value === "all" || event.status === eventFilter.value)
  );
  eventsEl.innerHTML = filtered.length ? filtered.map(event => `
    <tr><td>${dateLabel(event.timestamp)}</td><td>${hiveLabel(event.hive_id)}</td>
    <td class="${event.status === "ALARM" ? "event-critical" : ""}">${t(event.status === "ALARM" ? "Alarm" : event.status === "WATCH" ? "İzle" : "Normal")}</td>
    <td>${Math.round(event.anomaly_fraction * 100)}%</td>
    <td>${event.status !== "ALARM" ? "—" : event.acknowledged_at ? `<span class="acknowledged">${t("Kontrol edildi")}</span>` : `<button class="ack-button" data-ack="${event.id}" type="button">${t("Kontrol edildi olarak işaretle")}</button>`}</td></tr>`).join("") : `<tr><td colspan="5">${currentLanguage === "en" ? "No events match this filter." : "Filtreyle eşleşen olay yok."}</td></tr>`;
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
      return { x, y: 195 - event.anomaly_fraction * 170 };
    });
    const color = hiveColor(hiveId);
    return `<polyline class="chart-line" stroke="${color}" points="${points.map(point => `${point.x},${point.y}`).join(" ")}"/>${points.map(point => `<circle class="chart-point" fill="${color}" cx="${point.x}" cy="${point.y}" r="6"/>`).join("")}`;
  }).join("");
  svg.innerHTML = grid + (series || `<text class="chart-empty" x="450" y="110">${t("Grafik için olay bekleniyor")}</text>`);
}

function renderHiveDetail() {
  const hive = latestHives.find(item => item.hive_id === selectedHiveId);
  if (!hive) return;
  document.querySelector("#detail-title").textContent = hiveLabel(hive.hive_id);
  const status = document.querySelector("#detail-status");
  status.textContent = statusLabel(hive.durum);
  status.style.setProperty("--status", colors[hive.durum]);
  document.querySelector("#detail-summary").innerHTML = `
    <article><span>${t("Güncel durum")}</span><strong style="color:${colors[hive.durum]}">${statusLabel(hive.durum)}</strong></article>
    <article><span>${t("Aykırı ses penceresi")}</span><strong>${hive.anomaly_fraction == null ? "—" : Math.round(hive.anomaly_fraction * 100) + "%"}</strong></article>
    <article><span>${t("Son sinyal")}</span><strong>${dateLabel(hive.timestamp)}</strong></article>`;
  document.querySelector("#chart-legend").innerHTML = `<span style="--dot:${hiveColor(hive.hive_id)}">${hiveLabel(hive.hive_id)}</span>`;
  renderChart(latestEvents);
  renderEvents();
}

function showView(viewName, moveFocus = false) {
  const activeView = document.querySelector(`#${viewName}-view`);
  document.querySelectorAll(".app-view").forEach(view => { view.hidden = view !== activeView; });
  document.querySelectorAll(".nav-button").forEach(button => {
    const active = button.dataset.view === viewName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({top: 0, behavior: reduceMotion ? "auto" : "smooth"});
  if (moveFocus) {
    const heading = activeView?.querySelector("h2");
    if (heading) {
      heading.tabIndex = -1;
      heading.focus({preventScroll: true});
    }
  }
  if (viewName === "hives") refreshManagedHives();
  if (viewName === "alarms") refreshAlarms();
  if (viewName === "status") refreshSystemStatus();
  if (viewName === "settings") loadSettings();
}

function encodeWav(audioBuffer) {
  const channels = audioBuffer.numberOfChannels;
  const length = audioBuffer.length;
  const mono = new Float32Array(length);
  for (let channel = 0; channel < channels; channel += 1) {
    const values = audioBuffer.getChannelData(channel);
    for (let index = 0; index < length; index += 1) mono[index] += values[index] / channels;
  }
  const bytes = new ArrayBuffer(44 + length * 2);
  const view = new DataView(bytes);
  const write = (offset, value) => [...value].forEach((character, index) => view.setUint8(offset + index, character.charCodeAt(0)));
  write(0, "RIFF"); view.setUint32(4, 36 + length * 2, true); write(8, "WAVE");
  write(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, audioBuffer.sampleRate, true); view.setUint32(28, audioBuffer.sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, "data"); view.setUint32(40, length * 2, true);
  for (let index = 0; index < length; index += 1) {
    const sample = Math.max(-1, Math.min(1, mono[index]));
    view.setInt16(44 + index * 2, sample < 0 ? sample * 32768 : sample * 32767, true);
  }
  return new Blob([bytes], {type: "audio/wav"});
}

async function analyzeSensorAudio() {
  const file = sensorAudio.files[0];
  if (!managedHiveId || !sensorDevice.value) { sensorMessage.textContent = t("Önce bir cihaz ekleyin."); return; }
  if (!file) { sensorMessage.textContent = t("Önce bir ses kaydedin veya dosya seçin."); return; }
  sensorButton.disabled = true;
  sensorResult.hidden = true;
  sensorMessage.textContent = t("Ses hazırlanıyor…");
  let context;
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error(t("Ses dosyası tarayıcı tarafından açılamadı."));
    context = new AudioContextClass();
    const decoded = await context.decodeAudioData(await file.arrayBuffer());
    const wav = encodeWav(decoded);
    sensorMessage.textContent = managedEnrollment?.can_monitor ? t("ONNX modeli analiz ediyor…") : t("Sağlıklı başlangıç kaydı");
    const params = new URLSearchParams({hive_id: managedHiveId, device_id: sensorDevice.value, filename: file.name || "phone-recording.wav"});
    const response = await fetch(`/api/sensor-recordings?${params}`, {method: "POST", headers: {"Content-Type": "audio/wav"}, body: wav});
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || t("Ses analizi başarısız oldu"));
    const event = body.event;
    const enrollmentNote = body.model
      ? t("Kovana özel profil doğrulandı ve izleme etkinleştirildi.")
      : t("Sağlıklı başlangıç kaydı eklendi. Profil hazır olana kadar alarm üretilmez.");
    sensorResult.innerHTML = event
      ? `<strong>${t("Analiz tamamlandı")}: ${t(event.status === "WATCH" ? "İzle" : event.status === "ALARM" ? "Alarm" : "Normal")}</strong><span>${t("Aykırı ses")}: %${Math.round(event.anomaly_fraction * 100)}</span><span>${t("Pencere")}: ${body.windows}</span><span>${t("Kaynak")}: ${escapeHtml(body.model)}</span><p>${t("Yeni olay panele ve SQLite’a kaydedildi.")}</p>`
      : `<strong>${t("Sağlıklı başlangıç kaydı")}</strong><span>${t("Pencere")}: ${body.windows}</span><p>${enrollmentNote}</p>`;
    sensorResult.dataset.status = event ? event.status.toLowerCase() : "enrollment";
    sensorResult.hidden = false;
    sensorMessage.textContent = "";
    await Promise.all([refresh(), refreshAlarms(), openDevicePanel(managedHiveId)]);
  } catch (error) {
    sensorMessage.textContent = error.message || t("Ses analizi başarısız oldu");
  } finally {
    if (context) await context.close();
    sensorButton.disabled = false;
  }
}

function applySettings(settings) {
  currentSettings = settings;
  currentLanguage = settings.language || "tr";
  soundEnabled = settings.sound_enabled;
  refreshSeconds = settings.refresh_seconds;
  soundButton.textContent = t(`Sesli alarm: ${soundEnabled ? "açık" : "kapalı"}`);
  document.querySelector("#panel-name").textContent = settings.panel_name;
  document.title = `${settings.panel_name} | ${t("Kovan İzleme")}`;
  document.querySelector("#settings-panel-name").value = settings.panel_name;
  document.querySelector("#settings-location").value = settings.location_name;
  document.querySelector("#settings-sound").checked = settings.sound_enabled;
  document.querySelector("#settings-weather").checked = settings.weather_enabled;
  document.querySelector("#settings-refresh").value = String(settings.refresh_seconds);
  document.querySelector("#settings-language").value = currentLanguage;
  translatePage();
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

async function toggleLanguage() {
  if (!currentSettings) return;
  const language = currentLanguage === "tr" ? "en" : "tr";
  const response = await fetch("/api/settings", {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({...currentSettings, language}),
  });
  if (!response.ok) return;
  applySettings(await response.json());
  ["#hive-form-message", "#device-message", "#health-confirmation-message", "#sensor-message", "#settings-message"].forEach(selector => {
    const element = document.querySelector(selector);
    if (element) element.textContent = "";
  });
  alertEl.classList.remove("show");
  await Promise.all([refresh(), refreshContext(), refreshManagedHives(), refreshAlarms(), managedHiveId ? openDevicePanel(managedHiveId) : Promise.resolve()]);
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
        alarm_threshold: currentSettings?.alarm_threshold || 0.85,
        sound_enabled: form.sound_enabled.checked,
        refresh_seconds: Number(form.refresh_seconds.value),
        onboarding_completed: currentSettings?.onboarding_completed || false,
        weather_enabled: form.weather_enabled.checked,
        language: form.language.value,
      }),
    });
    if (!response.ok) throw new Error(t("Ayarlar kaydedilemedi"));
    applySettings(await response.json());
    message.textContent = t("Ayarlar kaydedildi ve hemen uygulanmaya başladı.");
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
  overview.innerHTML = `<span class="status-pulse"></span><div><strong>${t(data.overall === "ok" ? "Tüm sistemler çalışıyor" : "Sistem çalışıyor, bazı bağlantılar veri bekliyor")}</strong><p>${t(data.overall === "ok" ? "Panel ve bütün entegrasyonlar güncel veri üretiyor." : "Bekleyen bileşenlerin ayrıntılarını aşağıda görebilirsiniz.")}</p></div>`;
  const statusLabels = {ok: "Çalışıyor", waiting: "Veri bekleniyor", warning: "Kontrol gerekli"};
  document.querySelector("#status-components").innerHTML = data.components.map(component => `
    <article class="status-card ${component.status}">
      <span class="component-dot" aria-hidden="true"></span>
      <div><div class="status-card-title"><h3>${escapeHtml(td(component.name))}</h3><span>${t(statusLabels[component.status])}</span></div><strong>${escapeHtml(td(component.summary))}</strong><p>${escapeHtml(td(component.detail))}</p>${component.last_seen_at ? `<small>${t("Son bağlantı")}: ${dateLabel(component.last_seen_at)}</small>` : ""}</div>
    </article>`).join("");
  document.querySelector("#status-updated").textContent = `${t("Son kontrol")}: ${dateLabel(data.generated_at)}`;
  const header = document.querySelector(".connection");
  header.classList.toggle("attention", data.overall !== "ok");
  header.querySelector(".connection-label").textContent = t(data.overall === "ok" ? "Sistem bağlı" : "Sistem çalışıyor");
}

async function refreshSystemStatus() {
  const button = document.querySelector("#refresh-status");
  button.disabled = true;
  try {
    const response = await fetch("/api/system-status");
    if (!response.ok) throw new Error(t("Sistem durumu alınamadı"));
    renderSystemStatus(await response.json());
  } catch (error) {
    document.querySelector("#status-overview").innerHTML = `<span class="status-pulse"></span><div><strong>${t("Durum alınamadı")}</strong><p>${escapeHtml(error.message)}</p></div>`;
  } finally {
    button.disabled = false;
  }
}

function openHiveDetail(hiveId) {
  selectedHiveId = hiveId;
  showView("detail", true);
  renderHiveDetail();
}

function renderManagedHives() {
  managedHives.innerHTML = managedHivesData.length ? managedHivesData.map(hive => `
    <article class="managed-hive-row ${hive.active ? "" : "archived"}">
      <div><strong>${escapeHtml(displayHiveName(hive.name))}</strong><span>${hive.location ? escapeHtml(t(hive.location)) : t("Konum belirtilmedi")}</span></div>
      <div class="managed-hive-actions">
        <code>${hive.hive_id}</code>
        ${hive.active ? `<button data-manage-device="${hive.hive_id}" type="button">${t("Cihazlar ve model")}</button><button data-edit-hive="${hive.hive_id}" type="button">${t("Düzenle")}</button><button class="archive-button" data-archive-hive="${hive.hive_id}" type="button">${t("Pasif hâle getir")}</button>` : `<span class="archived-label">${t("Arşivlendi")}</span><button data-restore-hive="${hive.hive_id}" type="button">${t("Yeniden etkinleştir")}</button>`}
      </div>
    </article>`).join("") : `<p>${t("Henüz kovan eklenmedi.")}</p>`;
}

async function openDevicePanel(hiveId) {
  managedHiveId = hiveId;
  const hive = managedHivesData.find(item => item.hive_id === hiveId);
  const [devicesResponse, enrollmentResponse] = await Promise.all([
    fetch(`/api/hives/${hiveId}/devices`), fetch(`/api/hives/${hiveId}/enrollment`),
  ]);
  if (!devicesResponse.ok || !enrollmentResponse.ok) return;
  managedDevices = await devicesResponse.json();
  managedEnrollment = await enrollmentResponse.json();
  const panel = document.querySelector("#hive-device-panel");
  panel.hidden = false;
  document.querySelector("#device-panel-title").textContent = `${displayHiveName(hive?.name || hiveId)} · ${hiveId}`;
  const labels = {device_required: "Cihaz bekleniyor", enrolling: "Öğrenme devam ediyor", ready: "Profil hazır", monitoring: "İzleme etkin"};
  document.querySelector("#enrollment-status").innerHTML = `
    <div><strong>${t(labels[managedEnrollment.state])}</strong><span>%${managedEnrollment.progress_percent}</span></div>
    <progress max="100" value="${managedEnrollment.progress_percent}"></progress>
    <p>${managedEnrollment.can_monitor
      ? t("Bu kovanın profili hazır; yeni kayıtlar izleme ve alarm akışında değerlendirilir.")
      : `${managedEnrollment.recording_count}/${managedEnrollment.required_recordings} ${t("kayıt")} · ${managedEnrollment.recording_days}/${managedEnrollment.required_days} ${t("gün")} · ${managedEnrollment.confirmation_count}/${managedEnrollment.required_confirmations} ${t("saha doğrulaması")}. ${t("Profil hazır olana kadar alarm üretilmez.")}`}</p>`;
  sensorDevice.innerHTML = managedDevices.filter(device => device.active).map(device => `<option value="${device.device_id}">${escapeHtml(device.name)} · ${device.device_id}</option>`).join("");
  document.querySelector("#sensor-card").hidden = managedDevices.length === 0;
  document.querySelector("#health-confirmation-form").hidden = !managedEnrollment.confirmation_due;
  document.querySelector("#device-form").hidden = false;
  panel.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
}

async function addDevice(event) {
  event.preventDefault();
  if (!managedHiveId) return;
  const message = document.querySelector("#device-message");
  const response = await fetch(`/api/hives/${managedHiveId}/devices`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name: document.querySelector("#device-name").value.trim(), kind: document.querySelector("#device-kind").value}),
  });
  if (!response.ok) { message.textContent = t("Cihaz eklenemedi"); return; }
  message.textContent = t("Cihaz kovana bağlandı. Sağlıklı başlangıç kayıtlarını toplamaya başlayabilirsiniz.");
  await openDevicePanel(managedHiveId);
}

async function saveHealthConfirmation(event) {
  event.preventDefault();
  if (!managedHiveId) return;
  const message = document.querySelector("#health-confirmation-message");
  const response = await fetch(`/api/hives/${managedHiveId}/health-confirmations`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      evidence: document.querySelector("#health-evidence").value,
      note: document.querySelector("#health-note").value.trim() || null,
    }),
  });
  if (!response.ok) { message.textContent = t("Saha kontrolü kaydedilemedi"); return; }
  message.textContent = t("Saha kontrolü kaydedildi.");
  document.querySelector("#health-note").value = "";
  await openDevicePanel(managedHiveId);
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
    if (!response.ok) throw new Error(t("Kovan kaydedilemedi"));
    const hive = await response.json();
    const successMessage = editingHiveId ? `${hive.name} güncellendi.` : `${hive.name} ${hive.hive_id} kimliğiyle eklendi.`;
    editingHiveId = null;
    hiveForm.reset();
    document.querySelector("#hive-form-title").textContent = t("Yeni kovan ekle");
    document.querySelector("#save-hive-button").textContent = t("Kovanı kaydet");
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
  document.querySelector("#save-hive-button").textContent = t("Değişiklikleri kaydet");
  document.querySelector("#hive-name").focus();
}

async function setHiveActive(hiveId, active) {
  const action = active ? "restore" : "archive";
  const response = await fetch(`/api/hives/${hiveId}/${action}`, {method: "POST"});
  if (!response.ok) throw new Error(t("Kovan durumu değiştirilemedi"));
  await refresh();
  await refreshManagedHives();
}

function resetHiveForm() {
  editingHiveId = null;
  hiveForm.hidden = true;
  hiveForm.reset();
  document.querySelector("#hive-form-title").textContent = t("Yeni kovan ekle");
  document.querySelector("#save-hive-button").textContent = t("Kovanı kaydet");
  document.querySelector("#hive-form-message").textContent = "";
}

async function startDemo() {
  demoButton.disabled = true;
  demoButton.textContent = t("Demo hazırlanıyor…");
  try {
    const response = await fetch("/api/demo", { method: "POST" });
    if (!response.ok) throw new Error(t("Demo başlatılamadı"));
    await refresh();
  } finally {
    demoButton.disabled = false;
    demoButton.textContent = t("Demo senaryosunu başlat");
  }
}

function renderWeather(weather) {
  document.querySelector("#weather-location").textContent = weather.location;
  document.querySelector("#weather-temp").textContent = `${Math.round(weather.temperature_c)}°`;
  document.querySelector("#weather-details").innerHTML = `<span>${t("Nem")} %${weather.humidity_percent}</span><span>${t("Rüzgâr")} ${Math.round(weather.wind_kmh)} km/h</span>`;
}

function renderWeatherDisabled() {
  document.querySelector("#weather-location").textContent = t("Çevrimiçi hava durumu kapalı");
  document.querySelector("#weather-temp").textContent = "—";
  document.querySelector("#weather-details").innerHTML = `<span>${t("Temel kovan izleme internet olmadan çalışmaya devam eder.")}</span>`;
}

function renderReports(reports) {
  const matching = reports.filter(report => (report.language || "tr") === currentLanguage);
  latestReports = matching.length ? matching : reports;
  reportSelect.innerHTML = reports.length ? reports.map((report, index) => `<option value="${report.id}">${index === 0 ? t("Son rapor") : dateLabel(report.period_end)}</option>`).join("") : `<option value="">${t("Rapor yok")}</option>`;
  renderSelectedReport();
}

function renderSelectedReport() {
  const report = latestReports.find(item => String(item.id) === reportSelect.value) || latestReports[0];
  if (!report) return;
  document.querySelector("#report-period").textContent = `${dateLabel(report.period_start)} – ${dateLabel(report.period_end)}`;
  document.querySelector("#report-source").textContent = `${report.language === "en" ? t("İngilizce rapor") : t("Türkçe rapor")} · ${t("Üretici")}: ${report.generator || "manual"}`;
  document.querySelector("#report-summary").textContent = explainHiveIds(report.summary);
  document.querySelector("#report-actions").innerHTML = report.recommendations.map(item => `<li>${escapeHtml(explainHiveIds(item))}</li>`).join("");
  translatePage(document.querySelector("#reports-view"));
}

async function acknowledgeEvent(eventId) {
  const response = await fetch(`/api/events/${eventId}/acknowledge`, { method: "POST" });
  if (!response.ok) throw new Error(t("Alarm onaylanamadı"));
  await refresh();
  await refreshAlarms();
}

function renderAlarms() {
  const criticalEvents = alarmEvents.filter(event => event.status === "ALARM");
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
        <div class="alarm-card-head"><div><strong>${escapeHtml(hiveLabel(event.hive_id))}</strong><span>${dateLabel(event.timestamp)}</span></div><span class="alarm-confidence">%${Math.round(event.anomaly_fraction * 100)} ${t("aykırı ses")}</span></div>
        <h3>${t("Kalıcı akustik değişim")}</h3>
        <p>${event.acknowledged_at ? `${t("Kontrol edildi")}: ${dateLabel(event.acknowledged_at)}` : t("Kovanın fiziksel olarak kontrol edilmesi öneriliyor.")}</p>
      </div>
      ${event.acknowledged_at ? `<span class="resolved-label">${t("Kontrol edildi")}</span>` : `<button class="ack-button alarm-ack-button" data-alarm-ack="${event.id}" type="button">${t("Kontrol edildi olarak işaretle")}</button>`}
    </article>`).join("") : `<div class="empty-state"><strong>${t(alarmFilter.value === "open" ? "Açık alarm yok" : "Bu filtrede alarm yok")}</strong><p>${t("Kovanlarınızın kritik olayları burada görünecek.")}</p></div>`;
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
    if (!dashboardResponse.ok) throw new Error(t("API yanıt vermedi"));
    render(await dashboardResponse.json());
  } catch (error) {
    updatedEl.textContent = t("Bağlantı kurulamadı");
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
  soundButton.textContent = t(`Sesli alarm: ${soundEnabled ? "açık" : "kapalı"}`);
});
demoButton.addEventListener("click", startDemo);
sensorButton.addEventListener("click", analyzeSensorAudio);
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
  showView("overview", true);
});
document.querySelectorAll(".nav-button").forEach(button => button.addEventListener("click", () => {
  selectedHiveId = null;
  showView(button.dataset.view, true);
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
  const deviceButton = event.target.closest("[data-manage-device]");
  const editButton = event.target.closest("[data-edit-hive]");
  const archiveButton = event.target.closest("[data-archive-hive]");
  const restoreButton = event.target.closest("[data-restore-hive]");
  if (deviceButton) openDevicePanel(deviceButton.dataset.manageDevice);
  if (editButton) openEditHive(editButton.dataset.editHive);
  if (archiveButton) setHiveActive(archiveButton.dataset.archiveHive, false);
  if (restoreButton) setHiveActive(restoreButton.dataset.restoreHive, true);
});
document.querySelector("#device-form").addEventListener("submit", addDevice);
document.querySelector("#health-confirmation-form").addEventListener("submit", saveHealthConfirmation);
document.querySelector("#close-device-panel").addEventListener("click", () => {
  document.querySelector("#hive-device-panel").hidden = true;
  managedHiveId = null;
});
alarmsList.addEventListener("click", event => {
  const button = event.target.closest("[data-alarm-ack]");
  if (button) acknowledgeEvent(button.dataset.alarmAck);
});
document.querySelector("#refresh-status").addEventListener("click", refreshSystemStatus);
document.querySelector("#restore-backup").addEventListener("click", restoreBackup);
document.querySelector("#settings-form").addEventListener("submit", saveSettings);
document.querySelector("#language-toggle").addEventListener("click", toggleLanguage);
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
