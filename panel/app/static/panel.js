// A session can end while the panel is open: the password was changed on another device,
// or the owner deactivated this worker. The server answers 401, and every caller would
// otherwise show its own confusing failure. Sending the browser to the sign-in screen once
// is the honest response, and it must happen only once no matter how many calls fail.
const nativeFetch = window.fetch.bind(window);
let signedOut = false;
window.fetch = async (...args) => {
  const response = await nativeFetch(...args);
  const url = typeof args[0] === "string" ? args[0] : args[0]?.url ?? "";
  if (response.status === 401 && url.startsWith("/api/") && !url.startsWith("/api/login") && !signedOut) {
    signedOut = true;
    window.location.replace("/login");
  }
  return response;
};

const hivesEl = document.querySelector("#hives");
const eventsEl = document.querySelector("#events");
const updatedEl = document.querySelector("#updated");
const alertEl = document.querySelector("#alert");
const soundButton = document.querySelector("#sound-toggle");
const eventFilter = document.querySelector("#event-filter");
const reportSelect = document.querySelector("#report-select");
const reportPickerButton = document.querySelector("#report-picker-button");
const reportPickerMenu = document.querySelector("#report-picker-menu");
const reportPdfDownload = document.querySelector("#report-pdf-download");
const hiveForm = document.querySelector("#hive-form");
const managedHives = document.querySelector("#managed-hives");
const alarmsList = document.querySelector("#alarms-list");
const alarmFilter = document.querySelector("#alarm-filter");
const alarmHiveSearch = document.querySelector("#alarm-hive-search");
const overviewAlert = document.querySelector("#overview-alert");
const overviewAlertTitle = document.querySelector("#overview-alert-title");
const overviewAlertCopy = document.querySelector("#overview-alert-copy");
const sensorDevice = document.querySelector("#sensor-device");
const sensorAudio = document.querySelector("#sensor-audio");
const sensorButton = document.querySelector("#analyze-sensor-audio");
const sensorMessage = document.querySelector("#sensor-message");
const sensorResult = document.querySelector("#sensor-result");
let soundEnabled = true;
let refreshSeconds = 5;
let refreshTimer = null;
let currentSettings = null;
let lastCriticalId;  // undefined until the first dashboard arrives; see refresh()
let latestEvents = [];
let reportEvents = [];
let latestReports = [];
let allReports = [];
let activeReportType = "all";
let latestHives = [];
let managedHivesData = [];
let managedEnrollmentByHive = {};
const justCompletedHives = new Set();
const completingHives = new Map();
// Demo mode only: a real hive needs weeks of recordings before its profile trains, which
// no demo can wait for. Hives whose profile "finished" during the demo are kept here so
// the row stays at a trained profile instead of snapping back to the real percentage.
// `demoAvailable` is the server's answer and never changes; `demoMode` is which channel is
// on screen right now. The switch flips only the second one, so a presenter can show the
// finished profile and the real enrollment side by side without restarting anything.
let currentRole = "owner";
let managesAccounts = false;
let workerPreview = false;
let demoAvailable = false;
let demoMode = false;
const demoCompletedHives = new Set();
// Baseline collection is a queue, not a single file: a hive needs dozens of recordings,
// and they can come from picked files or from the device microphone listening live.
let sensorSource = "file";
let liveClips = [];
// Names identify a clip when a failed batch is re-queued, so the counter never rewinds —
// reusing "canli-kayit-2" after a removal would keep the wrong clip on a retry.
let liveClipCounter = 0;
let mediaRecorder = null;
let liveMeter = null;
let alarmEvents = [];
const collapsedAlarmHives = new Set();
// Older alarms on a hive collapse to a row; these are the ones a person opened back up.
const expandedAlarms = new Set();
// The alarm closed a moment ago, held open long enough to show what was recorded before
// it joins the rows below. Closing one is the end of a job, and a row appearing in its
// place with no acknowledgement reads as the click having gone nowhere.
let justResolvedAlarm = "";
let justResolvedTimer = 0;
// Long enough to read what was recorded, short enough not to be waited on.
const JUST_RESOLVED_MS = 3200;
const ALARM_SETTLE_MS = 420;
let selectedHiveId = null;
let editingHiveId = null;
let currentLanguage = "tr";
let managedHiveId = null;
let managedDevices = [];
let managedEnrollment = null;
let currentDisplayName = "arıcı";
let pendingAlarmId = null;

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
  "Günaydın": "Good morning", "İyi günler": "Good afternoon", "İyi akşamlar": "Good evening",
  "kovan izleniyor": "hives monitored", "Kovan durum özeti": "Hive status summary", "Bugün kovanlıkta": "In the apiary today", "Canlı akustik durum özeti": "Live acoustic status summary",
  "Sağlıklı": "Healthy", "İzleniyor": "Watching", "Açık alarm": "Open alarm", "Tümünü görüntüle →": "View all →",
  "Kovan dikkat istiyor": "Hive needs attention", "Kalıcı akustik değişim algılandı. Fiziksel kontrol önerilir.": "Persistent acoustic change detected. A physical inspection is recommended.", "Olayı incele": "Review event",
  "Ses profili sağlıklı referans aralığında.": "Sound profile is within the healthy reference range.", "Değişimin kalıcılık süresi takip ediliyor.": "The duration of the change is being monitored.",
  "Kalıcı değişim algılandı; fiziksel kontrol önerilir.": "Persistent change detected; a physical inspection is recommended.", "İlk akustik veri bekleniyor.": "Waiting for the first acoustic event.",
  "Veri bekleniyor…": "Waiting for data…", "Toplam kovan": "Total hives", "Normal": "Normal", "Uyarı": "Watch", "Kritik": "Critical", "Veri yok": "No data",
  "Detaylarını görmek istediğiniz kovanı seçin.": "Select a hive to view its details.",
  "SAHA BAĞLAMI": "FIELD CONTEXT", "Hava durumu": "Weather", "Yükleniyor…": "Loading…",
  "Tüm kovanlara dön": "Back to all hives", "KOVAN DETAYI": "HIVE DETAIL", "Kovan": "Hive",
  "Veri bekleniyor": "Waiting for data", "EĞİLİM": "TREND", "Akustik değişim oranı": "Acoustic change ratio",
  "TELEMETRİ": "TELEMETRY", "Son olaylar": "Recent events", "Durum": "Status", "Tümü": "All",
  "İzle": "Watch", "Alarm": "Alarm", "Sesli alarm: açık": "Audible alarm: on", "Sesli alarm: kapalı": "Audible alarm: off",
  "Zaman": "Time", "Aykırı ses": "Anomalous audio", "İşlem": "Action", "Henüz olay yok.": "No events yet.",
  // Two percentages sit side by side in the same row, so the header carries the sentence
  // that says which question each of them answers.
  "Sapma şiddeti": "Severity",
  "Çalıştığı birim": "Running on", "Şu ana kadar yazılan": "Written so far", "karakter": "characters",
  "Sapma şiddeti, sesin normal aralığın ne kadar dışına çıktığını gösterir; aykırı ses oranı ise kaydın ne kadarının dışarıda kaldığını.": "Severity is how far the sound moved outside its normal range; the anomalous-audio ratio is how much of the recording fell outside it.",
  "YAPAY ZEKÂ RAPORU": "AI REPORT", "HAFTALIK KOVAN RAPORU": "WEEKLY HIVE REPORT", "Haftalık değerlendirmeler": "Weekly assessments",
  "KOVAN RAPORLARI": "HIVE REPORTS", "Kovanlarda ne oldu?": "What happened in the hives?", "Yerel yapay zekâ değerlendirmesi": "Local AI assessment", "Olay özeti": "Event summary", "Günün özeti": "Daily summary",
  "Rapor geçmişi": "Report history", "Rapor yok": "No reports", "Son rapor": "Latest report", "Rapor filtreleri": "Report filters", "Rapor türü": "Report type", "Rapor geçmişinde ara": "Search report history", "Filtreleri uygula": "Apply filters", "rapor eşleşti": "reports matched", "İngilizce PDF": "English PDF", "Türkçe PDF": "Turkish PDF", "kayıt": "records", "Öğrenme sürüyor": "Learning", "Kovanı öğreniyor": "Learning this hive", "Saha doğrulaması bekleniyor": "Field check required", "Öğrenme, kovana bir dinleme cihazı eklendiğinde başlar.": "Learning starts once a listening device is added to the hive.", "Kayıt toplamaya devam etmek için kovanı yerinde kontrol edip sonucu girin.": "Inspect the hive on site and record the result to keep collecting.", "Cihaz ekle": "Add device", "Kayıt gönder": "Send recording", "Model eğitiliyor": "Training the model", "Kayıt gönderiliyor ve profil çıkarılıyor…": "Uploading the recording and building the profile…", "Sunucu üç dakika içinde yanıt vermedi. Sunucu günlüğünü kontrol edin.": "The server did not respond within three minutes. Check the server log.", "Sunucuya ulaşılamadı. Panel çalışıyor mu?": "Could not reach the server. Is the panel running?", "Profil eğitilemedi": "Profile could not be trained", "Eşikler doldu ancak model eğitimi tamamlanamadı. Birkaç kayıt daha gönderin; sorun sürerse sunucu günlüğüne bakın.": "The thresholds are met but training did not complete. Send a few more recordings; if it persists, check the server log.", "Toplanan kayıtlardan kovana özel akustik profil çıkarılıyor.": "Building this hive's own acoustic profile from the collected recordings.", "Profil hazır": "Profile ready", "Kovana özel akustik model eğitildi. Bu kovan artık izleniyor ve gerekirse alarm üretebilir.": "The hive's own acoustic model has been trained. This hive is now monitored and can raise an alarm when needed.", "Kaydı gönderin": "Send the recording", "Dosya yerel modelde çözümlenir; öğrenme sürüyorsa kayıt profile eklenir, profil hazırsa izleme akışında değerlendirilir.": "The file is analysed by the local model; while learning it is added to the profile, and once the profile is ready it is evaluated in the monitoring flow.", "Kovanı kaydet ve cihaz ekle": "Save hive and add device", "Sıradaki adım: cihaz eşleştirme": "Next step: pair a device", "Kaydettikten sonra kovana bir dinleme cihazı bağlayacaksınız. Öğrenme o adımda başlar ve": "After saving you will connect a listening device to the hive. Learning starts at that step and", "iPhone’da Sesli Notlar ile kaydedip dosyayı seçin ya da bilgisayarınızdaki bir WAV klasöründen yükleyin. Kayıt yalnızca yerel Waggle sunucusuna gönderilir, internete çıkmaz.": "Record with Voice Memos on iPhone and pick the file, or upload from a WAV folder on your computer. The recording goes only to the local Waggle server and never leaves your network.", "profil hazır olana kadar hiç alarm üretilmez": "no alarm is raised until the profile is ready", "Elinizde donanım yoksa “WAV klasörü” seçin: önceden alınmış ses kayıtlarını yükleyerek aynı akışı çalıştırabilirsiniz.": "No hardware yet? Choose \"WAV folder\" and upload previously captured recordings to run the same flow.", "Öne çıkan bulgu": "Key finding", "Dağılım": "Distribution", "Kalıcı olarak sil": "Delete permanently", "GERİ ALINAMAZ": "CANNOT BE UNDONE", "Kovanı kalıcı olarak sil": "Delete hive permanently", "Silinecek olay": "Events to delete", "Silinecek cihaz": "Devices to delete", "Kovan silindi": "Hive deleted", "olay": "events", "Kovan bilgisi alınamadı": "Could not read hive details", "Filtreler hangi raporun açılacağını belirler.": "Filters decide which report opens.", "Doğrulandı": "Confirmed", "Sorun yok": "No issue", "Tekrar kontrol": "Recheck", "Deterministik yedek motor": "Deterministic fallback engine", "Yapay zekâ modeline ulaşılamadı": "AI model was unreachable", "Yerelde işlendi": "Processed locally", "Kaynak kaydı yok · SQLite olay geçmişi": "No sources recorded · SQLite event history", "Metin yerel model tarafından yazıldı": "Text written by the local model", "Metni model yazdı": "Model wrote the text", "Yerel modelle": "With the local model", "Rapor geçmişi": "Report history", "Dönemi değiştir": "Change period", "GÜNCEL RAPOR": "CURRENT REPORT", "Hazırlayan": "Prepared by", "Karar deterministik doğrulayıcıdan geldi": "Decision came from the deterministic validator", "Yeni rapor üret": "Generate new report", "Rapor üretiliyor…": "Generating report…", "Rapor üretiliyor": "Generating report", "Yanıt gelmiyor…": "No response yet…", "Yanıt gelmiyor": "No response yet", "Model uzun süredir yanıt vermiyor; sunucu günlüğünü kontrol edin.": "The model has not responded for a long time; check the server log.", "Rapor üretilemedi": "Report generation failed", "rapor üretildi": "reports generated", "Bu dönemde rapor üretilecek olay bulunmadı": "No events to report in this period",
  "Türkçe rapor": "Turkish report", "İngilizce rapor": "English report", "Üretici": "Generator",
  "Haftalık değerlendirme": "Weekly assessment", "Rapor dönemi": "Report period", "Yerel yapay zekâ": "Local AI",
  "Bu hafta kovanlarda ne oldu?": "What happened in the hives this week?", "Akustik olaylar, saha kontrolleri ve önerilen adımlar tek bir değerlendirmede.": "Acoustic events, field inspections, and recommended actions in one assessment.",
  "YAPAY ZEKÂ ÖZETİ": "AI SUMMARY", "Kovanı kontrol et": "Inspect the hive",
  "İki yerel model aynı kararda birleşti.": "Two local models reached the same decision.",
  "Tek yerel modelin kararı; çapraz doğrulama yapılmadı.": "One local model's decision; no cross-check was made.",
  "Model cihazda çalışıyor. Bu donanımda genellikle 3–5 dakika sürer; bu sırada paneli kullanmaya devam edebilirsiniz.":
    "The model is running on this device; it usually takes three to five minutes on this hardware. The panel stays usable meanwhile.",
  "Model uzun süredir yanıt vermiyor. Sunucu günlüğüne bakın; panel çalışmaya devam ediyor.":
    "The model has not answered for a long time. Check the server log; the panel keeps working.",
  "İki yerel model farklı karar verdi; temkinli olan seçildi.": "The two local models disagreed; the more cautious reading was kept.",
  "YEREL KILAVUZ": "LOCAL GUIDANCE", "Değerlendirmelerin dayandığı notlar": "The notes assessments rest on",
  "Bu notlar cihazda saklanır ve internete çıkmaz. Bir rapor üretilirken döneme uyanlar seçilip modele verilir; modelin gördüğü tek dış bilgi budur.": "These notes live on this device and never leave it. When a report is generated the ones matching the period are selected and handed to the model; they are the only outside information it sees.",
  "Kılavuzda ara": "Search the guidance", "not": "notes", "Bu konuda not bulunamadı.": "No note matches that topic.", "Kılavuz": "Guidance",
  "MODEL KARARI": "MODEL DECISION", "Tespit edilen örüntü": "Pattern identified",
  "Kraliçe kaybıyla uyumlu": "Compatible with queen loss", "Fiziksel kontrol": "Physical inspection",
  "Önerilen eylemler": "Recommended actions", "Rutin": "Routine", "İzleme": "Watch", "Acil": "Immediate",
  "Normal aralıkta": "Within baseline", "Gelişen akustik değişim": "Developing acoustic change",
  "Kalıcı akustik değişim": "Persistent acoustic change",
  "Uyumlu olabilir, kesin tanı değil": "May be compatible; not a diagnosis", "Uyumlu değil": "Not compatible",
  "Gerekli": "Required", "Şu an gerekmiyor": "Not required now",
  "İzlemeye devam": "Keep monitoring", "Kaydı tekrarla": "Record again",
  "Kovanı fiziksel kontrol et": "Inspect the hive", "Kraliçeyi doğrula": "Verify the queen",
  "Saha doğrulamaları": "Field checks", "Yerel kılavuz tabanı": "Local guidance base",
  "Öğrenme kayıtları": "Enrollment recordings", "Cihazlar": "Devices",
  "Kovanın profilini oluşturan kayıtlar: hangi cihazdan, hangi gün, kaç pencere ve sağlıklı doğrulanıp doğrulanmadığı. 42 kayıt / 14 gün eşiğinin dayanağı budur. Ses dosyaları değil, yalnızca kayıt defteri.":
    "The recordings a hive's profile was built from: which device, which day, how many windows, and whether it was confirmed healthy. This is what the 42-recording, 14-day threshold rests on. The ledger, not the audio.",
  "Hangi mikrofonun hangi kovana bağlı olduğu, türü, etkinliği ve en son ne zaman kayıt gönderdiği.":
    "Which microphone belongs to which hive, its kind, whether it is active, and when it last sent a recording.",
  "Kovanı yerinde kontrol eden hesap, gözlem ve sonucun profile alınıp alınmadığı.": "The account that inspected the hive on site, what was observed, and whether the result entered the profile.",
  "Değerlendirmelerin dayandığı gözden geçirilmiş notlar, etiketleri ve seçim koşullarıyla.": "The reviewed notes an assessment can rest on, with their tags and selection conditions.",
  "DAYANDIĞI KILAVUZ": "GROUNDING NOTES", "Bu değerlendirme neye dayanıyor": "What this assessment rests on",
  "Yerel kılavuzdan bu döneme uyan notlar seçildi ve modele yalnızca bunlar verildi.": "The notes matching this period were selected from the local guidance, and only those were given to the model.",
  "Değerlendirilen dönem": "Assessment period", "Raporu hazırlayan": "Prepared by", "GENEL DURUM": "OVERALL STATUS", "Haftanın özeti": "Weekly summary", "SONRAKİ ADIMLAR": "NEXT STEPS", "Öncelikli öneriler": "Priority recommendations",
  "Waggle Yerel Rapor Motoru": "Waggle Local Report Engine",
  "SAHA GERİ BİLDİRİMİ": "FIELD FEEDBACK", "Sahada doğrulananlar": "Field-verified outcomes", "Seçili dönemde fiziksel olarak incelenen alarmların sonuçları.": "Outcomes of alerts physically inspected during the selected period.", "Yeniden kontrol gerekli": "Follow-up required", "Yerelde işlendi, kaynaklarla desteklendi": "Processed locally and grounded in sources",
  "Bu haftanın özeti": "This week's summary", "Önerilen adımlar": "Recommended actions", "Saha kontrolleri": "Field inspections",
  "Bu rapor döneminde kaydedilen alarm sonuçları": "Alert outcomes recorded during this report period",
  "Yerel ve kaynaklı": "Local and grounded", "SQLite olay geçmişi": "SQLite event history",
  "Ölçüm modeli": "Measurement model",
  "RAG ile kaynaklandırıldı": "Grounded with RAG", "Agent tarafından hazırlandı": "Prepared by Agent", "kaynak": "sources",
  "Waggle, akustik değişimleri erken uyarı olarak yorumlar; saha incelemesinin yerini almaz.": "Waggle interprets acoustic changes as early warnings; it does not replace field inspection.", "SORUMLULUK SINIRI": "SCOPE OF RESPONSIBILITY",
  "Henüz haftalık değerlendirme bulunmuyor. İlk rapor oluşturulduğunda kovanların durumu ve önerilen adımlar burada görünecek.": "No weekly assessment is available yet. Hive status and recommended actions will appear here when the first report is generated.",
  "Olay": "Event", "Günlük": "Daily", "Haftalık": "Weekly", "Tüm kovanlar": "All hives", "Başlangıç": "Start", "Bitiş": "End", "Filtreleri temizle": "Clear filters",
  "AKUSTİK EĞİLİM": "ACOUSTIC TREND", "Dönem içindeki değişim": "Change during the period", "OLAY DAĞILIMI": "EVENT DISTRIBUTION", "Durumlara göre kayıtlar": "Records by status", "DIŞA AKTAR": "EXPORT", "Raporu paylaşın": "Share this report", "Seçili değerlendirmeyi grafikleri ve kaynak bilgileriyle birlikte indirin.": "Download the selected assessment with charts and source details.", "PDF indir": "Download PDF",
  "ÖLÇÜM ÖZETİ": "MEASUREMENT SUMMARY", "Veriler ne söylüyor?": "What does the data show?", "Seçili rapor dönemi": "Selected report period",
  "Toplam kayıt": "Total records", "akustik olay": "acoustic events", "Ortalama aykırılık": "Average anomaly", "dönem ortalaması": "period average", "En yüksek değer": "Peak value", "ölçülen tepe": "observed peak", "Alarm oranı": "Alarm rate", "kritik kayıt payı": "share of critical records",
  "Aykırı ses oranının zaman içindeki değişimi": "Anomalous audio ratio over time", "Her nokta bir analiz penceresini, her renk ise ayrı bir kovanın dönem içindeki değişimini gösterir.": "Each point is an analysis window; each color shows the change of a separate hive during the period.", "Aykırı ses": "Anomalous audio", "Kayıtların durumlara göre dağılımı": "Distribution of records by status", "NORMAL, WATCH ve ALARM kararlarının seçili dönem içindeki payını karşılaştırır.": "Compares the share of NORMAL, WATCH and ALARM decisions during the selected period.",
  "KOVAN YÖNETİMİ": "HIVE MANAGEMENT", "+ Yeni kovan ekle": "+ Add new hive",
  "Yeni kovan ekle": "Add new hive", "Kovan adı": "Hive name", "Konum": "Location", "Vazgeç": "Cancel", "Kovanı kaydet": "Save hive",
  "Örn. Arka Bahçe Kovanı": "E.g. Backyard Hive", "Örn. Ankara / Gölbaşı": "E.g. Ankara / Gölbaşı",
  "ALARM MERKEZİ": "ALARM CENTER", "Kritik olaylar": "Critical events", "Göster": "Show",
  "Açık alarmlar": "Open alarms", "Kontrol edilenler": "Inspected", "Açık alarm": "Open alarms",
  "Açık alarmları fiziksel kovan kontrolünden sonra işaretleyin.": "Mark alarms only after a physical hive inspection.",
  "Dikkat isteyen olaylar": "Events requiring attention", "Fiziksel kontrol bekleniyor.": "Physical inspection pending.",
  "Alarm alan kovan": "Hive with alerts", "olay": "event", "olaylar": "events",
  "Açık": "Open", "Kontrol edilen": "Inspected", "KOVANLAR": "HIVES", "Alarm kayıtları": "Alert records", "Kovanlarda ara": "Search hives", "Kovan adı veya kimliği": "Hive name or ID",
  "Alarmı yalnızca kovanı yerinde inceledikten sonra kapatın.": "Close the alert only after inspecting the hive on site.",
  "Sesli uyarı açık": "Audible alert on", "Sesli uyarı kapalı": "Audible alert off", "Aktif": "Active",
  "dikkat istiyor": "requires attention", "Fiziksel kontrolü tamamla": "Complete physical inspection",
  "FİZİKSEL KONTROL": "PHYSICAL INSPECTION", "Kontrol sonucunu kaydedin": "Save inspection result",
  "Fiziksel incelemede gördüğünüz durumu seçin. Bu bilgi alarm geçmişine, dışa aktarımlara ve yapay zekâ raporlarına eklenir.": "Select what you observed during the physical inspection. This information is added to alert history, exports, and AI reports.",
  "Kontrol sonucu": "Inspection result", "Sorun doğrulandı": "Issue confirmed", "Kovanda müdahale gerektiren bir durum görüldü.": "A condition requiring intervention was observed in the hive.",
  "Sorun görülmedi": "No issue found", "Kovan kontrolünde belirgin bir sorun bulunmadı.": "No evident issue was found during hive inspection.",
  "Belirsiz": "Uncertain", "Sonuç kesin değil; yeniden kontrol gerekiyor.": "The result is inconclusive; another inspection is needed.",
  "Kısa not": "Short note", "isteğe bağlı": "optional", "Örn. Ana arı görüldü, koloni hareketli.": "E.g. Queen observed; colony active.",
  "Bir kontrol sonucu seçin.": "Select an inspection result.", "Sonucu kaydet": "Save result", "Vazgeç": "Cancel",
  "Waggle bir sağlık tanısı koymaz; kalıcı ses değişimini erken uyarı olarak bildirir.": "Waggle does not provide a health diagnosis; it reports persistent acoustic change as an early warning.",
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
  ,"Bahçe Kovanı": "Garden Hive", "Orman Kovanı": "Forest Hive", "Çayır Kovanı": "Meadow Hive"
  ,"Gölbaşı / Bahçe": "Gölbaşı / Garden", "Gölbaşı / Orman kenarı": "Gölbaşı / Forest edge", "Gölbaşı / Çayır": "Gölbaşı / Meadow"
  ,"Gölbaşı Arılığı": "Gölbaşı Apiary", "aykırı ses penceresi": "anomalous audio windows", "Detayları gör": "View details"
  ,"Son güncelleme": "Last updated", "Kovanın fiziksel olarak kontrol edilmesi öneriliyor.": "A physical hive inspection is recommended."
  ,"aykırı ses": "anomalous audio", "Açık alarm yok": "No open alarms", "Bu filtrede alarm yok": "No alarms match this filter"
  // Alarm kartının yeni düzeni
  ,"Kovanın alarmlarını aç veya kapat": "Show or hide this hive's alarms"
  ,"Alarm algılandı": "Alarm raised", "Fiziksel kontrol": "Physical inspection", "Sonucu kaydet": "Record the outcome"
  ,"Aykırı ses": "Anomalous audio", "Ölçülmedi": "Not measured"
  ,"Fiziksel kontrolü başlat": "Start the physical inspection", "Kovanı incele": "Open the hive"
  ,"sapma şiddeti": "severity", "Aykırı ses ölçülmedi": "Anomalous audio not measured", "Şiddet ölçülmedi": "Severity not measured"
  ,"Detayları aç": "Open details", "Yerel kılavuz": "Local guidance"
  // Kapanmış alarm kartı
  ,"Alarm kapandı": "No open alarms", "Kapandı": "Closed"
  ,"Fiziksel kontrol tamamlandı": "Physical inspection completed"
  ,"Alarm saha kontrolüyle kapatıldı. Yeni bir kalıcı değişim algılanırsa tekrar bildirim oluşturulur.": "The alarm was closed by a field inspection. A new alert is raised if another lasting change is detected."
  ,"Kayıt başarıyla kaydedildi": "The record was saved"
  ,"Kontrol sonucu": "Inspection outcome", "Belirgin sorun görülmedi": "No clear issue found"
  ,"Kontrol eden": "Inspected by", "Alarm anındaki ölçüm": "Measured when the alarm was raised"
  ,"Sonuç kaydedildi": "Outcome recorded"
  // Kovan detayı sayfası
  ,"Kesintisiz değişim": "Unbroken change", "sn": "s", "Alarm eşiği 30 saniyedir": "The alarm threshold is 30 seconds"
  ,"Kovanın son kaydına göre": "From this hive's latest record", "Acil kontrol önerilir": "An inspection is recommended"
  ,"Kaydın normal aralık dışında kalan bölümü": "How much of the recording fell outside the normal range"
  ,"Sesin normal profilden uzaklığı": "How far the sound moved from the normal profile"
  ,"Kalıcı akustik değişim sürüyor": "A lasting acoustic change is under way"
  ,"Alarm kaydını incele": "Review the alarm record"
  ,"Son 24 saatte": "In the last 24 hours", "Son 7 günde": "In the last 7 days", "Son 30 günde": "In the last 30 days"
  ,"Bu dönemde kayıt yok": "No records in this period"
  ,"Bu durumda ne yapmalı?": "What to do about this", "Yerel kılavuzu aç": "Open the local guidance"
  ,"Kovanı fiziksel olarak kontrol edin": "Inspect the hive physically"
  ,"Kraliçe ve yavru düzenini doğrulayın": "Verify the queen and the brood pattern"
  ,"Sonucu kaydedin": "Record what you found"
  ,"Yeni bir ses kaydı alın": "Take another recording"
  ,"Değişimin sürüp sürmediğine bakın": "See whether the change is continuing"
  ,"Sürerse fiziksel kontrole geçin": "Move to a physical inspection if it does"
  ,"Rutin akustik izlemeye devam edin": "Continue routine acoustic monitoring"
  ,"Kayıtları benzer saatlerde alın": "Record at similar times of day"
  ,"Mikrofonun yerini değiştirmeyin": "Leave the microphone where it is"
  ,"İzleme bilgisi": "Monitoring setup", "Model": "Model", "Sesli alarm": "Audible alarm"
  ,"Açık": "On", "Kapalı": "Off", "Kayıt yok": "No record"
  ,"Kovanlarınızın kritik olayları burada görünecek.": "Critical hive events will appear here."
  ,"Tüm sistemler çalışıyor": "All systems operational", "Sistem çalışıyor, bazı bağlantılar veri bekliyor": "System operational; some integrations are waiting for data"
  ,"Panel ve bütün entegrasyonlar güncel veri üretiyor.": "The panel and all integrations are producing current data."
  ,"Bekleyen bileşenlerin ayrıntılarını aşağıda görebilirsiniz.": "Details of pending components are shown below."
  ,"Çalışıyor": "Operational", "Kontrol gerekli": "Check required", "Son bağlantı": "Last connection", "Son kontrol": "Last checked"
  ,"Güncellendi": "Updated"
  ,"Canlı veri alınıyor": "Receiving live data", "Cihaz veya model sonuçları güvenli bağlantı üzerinden panele ulaşıyor.": "Device or model results are reaching the panel over a secure connection."
  ,"İlk veri bekleniyor": "Waiting for first event", "Kovan cihazı veya akustik analiz servisi ilk olayı gönderdiğinde bağlantı zamanı burada görünecek.": "The connection time will appear here after the hive device or acoustic analysis service sends its first event."
  ,"Cihaz verisi gecikiyor": "Device data is delayed", "Son olay beklenen süreden eski. Kovan cihazını, modeli ve yerel ağ bağlantısını kontrol edin.": "The latest event is older than expected. Check the hive device, model, and local network."
  ,"Akustik model (ONNX)": "Acoustic model (ONNX)", "Akustik model hazır": "Acoustic model ready"
  ,"Akustik model dosyası eksik": "Acoustic model file is missing", "Karar eşleşmesi doğrulanmadı": "Decision parity not verified"
  ,"karar eşleşmesi raporu bulunamadı": "no decision parity report found"
  ,"Rapor entegrasyonu çalışıyor": "Report integration operational", "Üretilen değerlendirme raporları panele kaydediliyor.": "Generated assessment reports are being stored in the panel."
  ,"İlk rapor bekleniyor": "Waiting for first report", "İlk haftalık değerlendirme gönderildiğinde burada son rapor zamanı görünecek.": "The latest report time will appear here after the first assessment is submitted."
  ,"Rapor güncel değil": "Report is outdated", "Son haftalık değerlendirme beklenen süreden eski. Rapor üretim akışını kontrol edin.": "The latest assessment is older than expected. Check the report generation flow."
  ,"Grafik için olay bekleniyor": "Waiting for events to plot", "Güncel durum": "Current status", "Son sinyal": "Latest signal", "Aykırı ses penceresi": "Anomalous audio windows"
  ,"Ayarlar kaydedilemedi": "Settings could not be saved", "Ayarlar kaydedildi ve hemen uygulanmaya başladı.": "Settings saved and applied immediately."
  ,"Sistem durumu alınamadı": "System status could not be loaded", "Durum alınamadı": "Status unavailable"
  ,"Konum belirtilmedi": "Location not specified", "Düzenle": "Edit", "Pasif hâle getir": "Deactivate", "Arşivlendi": "Archived", "Yeniden etkinleştir": "Reactivate", "Henüz kovan eklenmedi.": "No hives have been added yet."
  ,"Yeni kovan ekle": "Add new hive", "Kovanı kaydet": "Save hive", "Değişiklikleri kaydet": "Save changes"
  ,"Kovan kaydedilemedi": "Hive could not be saved", "Kovan durumu değiştirilemedi": "Hive status could not be changed"
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
  ,"Enlem": "Latitude", "Boylam": "Longitude"
  ,"Hava durumu bu koordinatlar için sorulur. Yukarıdaki ad yalnızca etikettir: ikisi ayrı yerleri gösterirse panel başka bir yerin havasını kovanlığınızın adıyla kaydeder.": "Weather is requested for these coordinates. The name above is only a label: if the two point at different places, the panel records another location's weather under your apiary's name."
  ,"Hava durumu alınamadı": "Weather unavailable"
  ,"Servise ulaşılamıyor. Kovan izleme bundan etkilenmez; kayıtlara hava bilgisi eklenmez.": "The service cannot be reached. Hive monitoring is unaffected; recordings are stored without weather."
  ,"Bu işlem mevcut kovan, olay, alarm, rapor ve ayarları seçilen yedekle değiştirecek. Devam edilsin mi?": "This replaces the current hives, events, alarms, reports and settings with the selected backup. Continue?"
  ,"Waggle’ın temel kullanım adımlarını yeniden görüntüleyin.": "Review Waggle's essential usage steps."
  ,"Kovanınızı ekleyin": "Add your hive", "Uyarıları takip edin": "Follow alerts", "Rapor ve yedekleri kullanın": "Use reports and backups"
  ,"Dört kısa adımda kovanlarınızı izlemeye başlayın.": "Start monitoring your hives in four short steps."
  ,"Bu rehberi daha sonra Ayarlar bölümünden tekrar açabilirsiniz.": "You can reopen this guide later from Settings."
  // Hızlı başlangıç rehberi (adım adım)
  ,"Kovanlarınızı izlemeye dört kısa adımda başlayın.": "Start monitoring your hives in four short steps."
  ,"Rehberi kapat": "Close the guide", "Bağlantı": "Connection", "Şimdilik geç": "Skip for now", "Geri": "Back", "Devam et": "Continue"
  ,"Bu rehberi Ayarlar’dan yeniden açabilirsiniz.": "You can reopen this guide from Settings."
  ,"İlk kovanınızı ekleyin": "Add your first hive"
  ,"Kovanınıza anlaşılır bir ad ve konum verin. Teknik sensör kimliğini Waggle otomatik oluşturur.": "Give your hive a clear name and location. Waggle creates the technical sensor ID for you."
  ,"Örn. Bahçe Kovanı": "E.g. Garden Hive", "Örn. Gölbaşı Arılığı": "E.g. Gölbaşı Apiary"
  ,"Yazdıklarınız yalnızca kovan ekleme formuna taşınır; kaydetme kararı sizde kalır.": "What you type is only carried into the add-hive form; saving stays your decision."
  ,"Kovan cihazından veya akustik analiz servisinden gelen olaylar güvenli biçimde panele aktarılır. Model, kovanın sağlıklı sesini öğrenene kadar hiç alarm üretmez.": "Events from the hive device or the acoustic analysis service are delivered securely to the panel. The model raises no alarm until it has learned the hive's healthy sound."
  ,"Bağlantı durumunu": "You can follow the connection status on the", "ekranından izleyebilirsiniz.": "screen."
  ,"Kalıcı bir akustik değişim görüldüğünde panel alarm açar. Kovanı yerinde inceleyin ve gördüğünüz sonucu alarma işleyin.": "When a persistent acoustic change appears, the panel raises an alarm. Inspect the hive on site and record what you saw on the alarm."
  ,"Alarmlar bölümü açık ve kontrol edilen kayıtları ayrı ayrı listeler.": "The Alarms section lists open and inspected records separately."
  ,"Haftalık değerlendirmeleri okuyun; gerektiğinde kayıtları dışa aktarın veya tam veritabanı yedeğini indirin.": "Read the weekly assessments; export records or download a full database backup when you need to."
  ,"Raporlar ve yedekler bu cihazda üretilir; hiçbir kayıt dışarı gönderilmez.": "Reports and backups are produced on this device; no record leaves it."
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
  ,"Cihaz adı": "Device name", "Cihaz türü": "Device type", "Saha telefonu": "Field phone", "Telefon mikrofonu": "Phone microphone"
  ,"Akustik sensör": "Acoustic sensor", "WAV klasörü": "WAV folder", "Cihazlar ve model": "Devices and model"
  ,"Bağlı cihaz": "Connected device", "Ses kaydı seçin": "Choose an audio recording", "Kaydı gönder": "Send recording"
  ,"iPhone’da Sesli Notlar ile kaydedip dosyayı seçin. Kayıt yalnızca yerel Waggle sunucusuna gönderilir.": "Record with Voice Memos on iPhone, then choose the file. Audio is sent only to the local Waggle server."
  ,"Waggle deneyimini kovanlığınıza göre düzenleyin.": "Tune the Waggle experience to your apiary."
  ,"adım": "steps", "tamamlandı": "completed", "henüz tamamlanmadı": "not completed yet", "Rehberi aç": "Open the guide", "Başlangıç rehberi": "Getting started"
  ,"Genel": "General", "Güvenlik": "Security", "Yerel kılavuz": "Local guidance", "Ekip": "Team", "Önerilen": "Recommended"
  ,"Ayar bölümleri": "Settings sections", "Kovanlığınız": "Your apiary", "Yenileme sıklığı": "Refresh interval"
  ,"Kaydedilmemiş değişiklikler var": "You have unsaved changes", "Tüm değişiklikler kaydedildi": "All changes saved"
  ,"kovan": "hives", "not": "notes"
  ,"2 sn": "2 s", "5 sn": "5 s", "10 sn": "10 s", "30 sn": "30 s", "60 sn": "60 s"
  ,"Kovandan rapora veri yolculuğu": "A recording's journey from hive to report"
  ,"Kontroller yerel ağda çalışır": "These checks run on the local network"
  ,"Bağlantı geçmişi": "Connection history", "Geçmişi gizle": "Hide history"
  ,"Bağlantı geçmişi alınamadı": "Could not read the connection history"
  ,"Bu bileşenden henüz hiç kayıt ulaşmadı.": "Nothing has arrived from this component yet."
  ,"Olay raporu": "Event report", "Günlük rapor": "Daily report"
  ,"Veri zinciri": "Data chain", "Bir kayıt mikrofondan panele bu sırayla ulaşır. Zincirin nerede durduğu buradan okunur.": "A recording travels from the microphone to the panel in this order. This is where you see where it stopped."
  ,"sağlıklı": "healthy", "veri bekliyor": "waiting for data", "kontrol gerekli": "need attention"
  ,"Sorun giderme adımları": "Troubleshooting steps", "Son veri": "Last data", "önce": "ago", "gecikti": "late", "beklenen aralık": "expected interval"
  ,"dakika": "minutes", "saat": "hours", "gün": "days"
  ,"Zincirin tamamı çalışıyor": "The whole chain is running", "Kayıtlar mikrofondan panele kadar kesintisiz ulaşıyor; yapılacak bir şey yok.": "Recordings reach the panel from the microphone without a break; nothing to do."
  ,"Kovan cihazları": "Hive devices", "Beklenen aralıkta yeni kayıt gelmedi; zincir burada duruyor.": "No new recording arrived within the expected interval; the chain stops here."
  ,"Kovan cihazının açık ve şarjlı olduğunu doğrulayın": "Check the hive device is powered and charged"
  ,"Cihazın yerel ağa bağlı olduğunu kontrol edin": "Check the device is connected to the local network"
  ,"Kovanlarım sayfasından elle bir kayıt göndererek zinciri sınayın": "Send a recording by hand from My Hives to test the chain"
  ,"Kovana bir dinleme cihazı ekleyin": "Add a listening device to the hive"
  ,"Kovanlarım sayfasından ilk kaydı gönderin": "Send the first recording from My Hives"
  ,"Foundry Local sunucusunun çalıştığını doğrulayın": "Check that the Foundry Local server is running"
  ,"Raporlar sayfasından elle bir rapor üretmeyi deneyin": "Try generating a report by hand from Reports"
  ,"Sunucu günlüğünde model çağrısının hatasına bakın": "Look for the model call's error in the server log"
  ,"Raporlar sayfasından ilk değerlendirmeyi üretin": "Generate the first assessment from Reports"
  ,"Dışa Aktar sayfasından hemen bir SQLite yedeği alın": "Take a SQLite backup now from Export"
  ,"Sağlam bir yedekten geri yükleyin": "Restore from a sound backup"
  ,"Kovan cihazları kayıtları panele göndermeye devam ediyor.": "Hive devices keep sending recordings to the panel."
  ,"Kovan cihazı ilk kaydı gönderdiğinde bağlantı zamanı burada görünecek.": "When the hive device sends its first recording, the connection time appears here."
  ,"Dosya seçilmedi": "No file chosen", "Dosya seç": "Choose file"
  ,"Operasyon": "Operations", "Sistem": "System", "Veri türü ara": "Search data types", "Veri türü grubu": "Data type group"
  ,"Aramanızla eşleşen veri türü yok.": "No data type matches your search.", "Biçim": "Format", "Dönem": "Period"
  ,"Tüm zamanlar": "All time", "Son 7 gün": "Last 7 days", "Son 30 gün": "Last 30 days", "Son 90 gün": "Last 90 days", "Son 1 yıl": "Last year"
  ,"Veri türü seçin": "Choose what to export", "veri türü seçildi": "data types selected", "Zip olarak indir": "Download as zip"
  ,"İndirmek istediğiniz kayıtları seçin. Birden fazla seçerseniz hepsi tek bir zip dosyasında iner.": "Choose the records you want. Pick more than one and they arrive together in a single zip."
  ,"bu veri türlerinin bir dönemi yoktur; seçilen aralıktan bağımsız olarak tamamı iner.": "these have no period of their own, so they are exported in full whatever range is chosen."
  ,"Model durumları, akustik değişim oranları, ölçüm koşulları ve zamanlar.": "Model decisions, acoustic change ratios, the conditions they were measured in, and their times."
  ,"Haftalık değerlendirmeler, model kararları ve dayandıkları kaynaklar.": "Weekly assessments, the model's decisions and the sources they rest on."
  ,"Kovanın profilini oluşturan kayıt defteri: hangi cihaz, hangi gün, kaç pencere. Ses dosyaları değil.": "The logbook behind a hive's profile: which device, which day, how many windows. Not the audio itself."
  ,"Hangi mikrofonun hangi kovana bağlı olduğu, türü ve en son ne zaman kayıt gönderdiği.": "Which microphone belongs to which hive, its kind, and when it last sent a recording."
  ,"Cihaz bekleniyor": "Waiting for device", "Öğrenme devam ediyor": "Learning in progress", "Profil hazır": "Profile ready", "İzleme etkin": "Monitoring active"
  ,"tamamlandı": "complete", "Kovana özel model": "Hive-specific model", "Gerekirse alarm": "Alarms when needed"
  ,"EKİP": "TEAM", "Çalışanlar": "Workers", "+ Çalışan ekle": "+ Add a worker", "Çalışanı ekle": "Add worker"
  ,"Çalışanlar kayıt gönderebilir, saha kontrolü girebilir ve alarmın fiziksel kontrolünü tamamlayabilir. Kovan ekleyip silemez, cihaz bağlayamaz, ayarları ve yedeği değiştiremez. Yaptıkları işlem kendi adlarıyla kaydedilir.": "Workers can send recordings, record field checks and complete the physical inspection of an alarm. They cannot add or delete hives, pair devices, or change settings and backups. Everything they do is recorded under their own name."
  ,"Adı soyadı": "Full name", "Geçici parola": "Temporary password"
  ,"Bu parolayı çalışana kendiniz iletirsiniz. İlk girişinde kendi parolasını belirlemeden hiçbir işlem yapamaz.": "You hand this password over yourself. Until they set their own at first sign-in, the account cannot do anything."
  ,"Henüz çalışan hesabı yok.": "No worker accounts yet.", "Etkin": "Active", "Devre dışı": "Disabled"
  ,"Parolasını belirlemedi": "Has not set a password", "Parola ver": "Issue a password"
  ,"Devre dışı bırak": "Disable", "Yeniden etkinleştir": "Re-enable", "Çalışan eklenemedi": "The worker could not be added"
  ,"eklendi. Geçici parolayı kendisine iletin.": "added. Hand the temporary password over."
  ,"için geçici parola (en az 10 karakter):": "— temporary password (at least 10 characters):"
  ,"Parola verilemedi": "The password could not be issued"
  ,"Geçici parola verildi. Çalışan ilk girişinde kendi parolasını belirleyecek.": "Temporary password issued. The worker sets their own at the next sign-in."
  ,"devre dışı bırakılsın mı? Açık oturumu da hemen kapanır.": "— disable this account? Their open session closes immediately."
  ,"Değişiklik uygulanamadı": "The change could not be applied"
  ,"İLK GİRİŞ": "FIRST SIGN-IN", "Kendi parolanızı belirleyin": "Choose your own password"
  ,"Hesabınız geçici bir parolayla açıldı ve o parolayı bir başkası da biliyor. Kendi parolanızı belirlemeden kayıt gönderemez, saha kontrolü giremez veya alarm kapatamazsınız.": "Your account was opened with a temporary password that somebody else also knows. Until you choose your own, you cannot send recordings, record field checks or close alarms."
  ,"Parolamı belirle": "Set my password", "Parolanız belirlendi. Artık kayıt gönderebilirsiniz.": "Your password is set. You can send recordings now."
  ,"Kurtarma kodu durumu okunamadı. Sayfayı yenileyin.": "The recovery code status could not be read. Reload the page."
  ,"HESAP GÜVENLİĞİ": "ACCOUNT SECURITY", "Parola ve kurtarma": "Password and recovery"
  ,"Parolayı değiştir": "Change password", "Güvenliğiniz için mevcut parolanız sorulur.": "Your current password is required."
  ,"En az 10 karakter": "At least 10 characters", "İki alan da aynı": "Both fields match", "Mevcut paroladan farklı": "Different from the current one"
  ,"Kurtarma kodu": "Recovery code", "kurtarma kodu": "recovery code"
  ,"Parolanızı unutursanız girişte bu kodla yeni parola belirlersiniz.": "If you forget your password, this code lets you set a new one at sign-in."
  ,"Bu kod yalnızca bir kez gösterilir. Bir yere yazın veya yazdırın.": "This code is shown only once. Write it down or print it."
  ,"Kopyala": "Copy", "Yazdır": "Print", "Kurtarma kodu üret": "Generate recovery code", "Yeni kod üret": "Generate a new code"
  ,"Kurtarma kodu tanımlı": "Recovery code is set", "Bu hesapta henüz kurtarma kodu yok.": "This account has no recovery code yet."
  ,"Bu hesap için kurtarma kodu tutulamıyor.": "A recovery code cannot be stored for this account."
  ,"Yeni kod üretilirse eski kurtarma kodu geçersiz olur. Devam edilsin mi?": "Generating a new code invalidates the old one. Continue?"
  ,"Kurtarma kodu üretilemedi": "The recovery code could not be generated"
  ,"Kod panoya kopyalandı.": "The code was copied to the clipboard.", "Kopyalanamadı; kodu elle not alın.": "Could not copy; write the code down manually."
  ,"Yazdırma penceresi açılamadı.": "The print window could not be opened."
  ,"Bu kod tek kullanımlıktır. Güvenli bir yerde saklayın.": "This code works once. Keep it somewhere safe."
  ,"Kodunuz da yoksa: panelin çalıştığı bilgisayarda": "No code either? On the computer running the panel, run"
  ,"komutunu çalıştırın.": "in the project folder."
  ,"Hesap parolası": "Account password", "Mevcut parola": "Current password", "Yeni parola": "New password"
  ,"Yeni parolayı doğrulayın": "Confirm new password", "Parolayı değiştir": "Change password"
  ,"Panel yerel çalıştığı için e-postayla sıfırlama yoktur; parolayı değiştirmek için mevcut parolanız gerekir.": "The panel runs locally, so there is no e-mail reset; changing the password requires your current one."
  ,"Yeni parolalar eşleşmiyor": "The new passwords do not match", "Parola değiştirilemedi": "Password could not be changed"
  ,"Parolanız değiştirildi. Bir sonraki girişte yeni parolayı kullanın.": "Your password has been changed. Use the new one at your next sign-in."
  ,"Demo görünümü": "Demo view", "Gerçek görünüm": "Real view"
  ,"Demo görünümü: profil tamamlanmış gibi gösteriliyor.": "Demo view: the profile is presented as if it were complete."
  ,"Gerçek görünüm: sunucudaki asıl öğrenme durumu gösteriliyor.": "Real view: the actual enrollment state on the server is shown."
  ,"Profil tamamlanmış gibi gösteriliyor": "The profile is presented as complete"
  ,"Sunucudaki gerçek öğrenme durumu": "The real enrollment state on the server"
  ,"Çalışan gözüyle bak": "Preview as a worker", "Önizlemeden çık": "Leave the preview"
  ,"Çalışan gözüyle bakıyorsunuz": "You are previewing a worker's panel"
  ,"Çalışanlara kapalı bölümler gizli. Yetkiniz değişmedi; işlemler yine sizin hesabınızla yapılır.": "Sections closed to workers are hidden. Your permissions are unchanged; actions still run under your own account."
  ,"Önizlemeyi kapat": "Close the preview"
  ,"Kayıt kaynağı": "Recording source", "Dosya yükle": "Upload files", "Cihazdan canlı dinle": "Listen live on this device"
  ,"Birden fazla dosya seçebilirsiniz; hepsi sırayla gönderilir. iPhone’da Sesli Notlar ile kaydedip dosyaları seçin ya da bilgisayarınızdaki bir WAV klasöründen yükleyin. Kayıtlar yalnızca yerel Waggle sunucusuna gönderilir, internete çıkmaz.": "You can pick several files; they are sent one after another. Record with Voice Memos on iPhone and choose the files, or upload from a WAV folder on your computer. The recordings go only to the local Waggle server and never leave your network."
  ,"Cihazın mikrofonu kovanı anlık dinler. Kaydı bitirdiğinizde kuyruğa eklenir; arka arkaya birkaç kayıt alabilirsiniz. Mikrofon yalnızca bu cihazda çalışır ve ses yerel sunucudan dışarı çıkmaz.": "The device microphone listens to the hive live. Each recording joins the queue when you stop it, so you can take several in a row. The microphone runs only on this device and the audio never leaves the local server."
  ,"Dinlemeyi başlat": "Start listening", "Dinlemeyi bitir": "Stop listening", "Kaydı çıkar": "Remove recording"
  ,"Kayıtları gönderin": "Send the recordings", "kaydı gönder": "recordings", "Kayıt gönderiliyor": "Sending recording"
  ,"Kayıtlar sırayla yerel modelde çözümlenir; öğrenme sürüyorsa profile eklenir, profil hazırsa izleme akışında değerlendirilir.": "The recordings are analysed one by one by the local model; while learning they are added to the profile, and once the profile is ready they are evaluated in the monitoring flow."
  ,"kayıt gönderilemedi": "recordings could not be sent", "sağlıklı başlangıç kaydı": "healthy baseline recordings"
  ,"Kayıt kuyruğa eklendi": "Recording added to the queue", "Kayıt çok kısa. En az 3 saniye dinletin.": "That recording is too short. Listen for at least 3 seconds."
  ,"Mikrofon yalnızca güvenli bağlantıda açılır. Bu cihazda paneli 127.0.0.1 üzerinden açın ya da telefonda kaydedip “Dosya yükle” sekmesinden gönderin.": "The microphone only opens on a secure connection. Open the panel at 127.0.0.1 on this device, or record on the phone and send it from the \"Upload files\" tab."
  ,"Bu tarayıcı mikrofon kaydını desteklemiyor. “Dosya yükle” sekmesini kullanın.": "This browser cannot record from the microphone. Use the \"Upload files\" tab."
  ,"Mikrofon izni verilmedi. Tarayıcı ayarlarından bu siteye mikrofon izni verin.": "Microphone access was denied. Allow this site to use the microphone in your browser settings."
  ,"Sağlıklı kayıt": "Healthy recordings", "Farklı gün": "Distinct days", "Saha doğrulaması": "Field confirmations"
  ,"Kovan sakinken alınmış kayıtlar. Tek seferde birden fazla dosya gönderebilirsiniz.": "Recordings taken while the hive is calm. You can send several files at once."
  ,"Takvim günü sayılır: aynı gün kaç kayıt gönderirseniz gönderin 1 gün eklenir.": "Counted per calendar day: however many recordings you send on one day, it still adds a single day."
  ,"Kovanı yerinde kontrol edip sonucu girdiğinizde eklenir; en fazla dört günde bir istenir.": "Added when you inspect the hive on site and record the result; asked at most once every four days."
  ,"Üç şart da dolmadan profil eğitilmez ve o zamana kadar hiç alarm üretilmez. Eksik kalırsa ilerleme olduğu yüzdede bekler, hiçbir şey kaybolmaz.": "The profile is not trained until all three thresholds are met, and no alarm is raised before that. If one stays short the progress simply waits at its current percentage; nothing is lost."
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
  // A component detail is a list of independent facts joined with "·". Translating each
  // one on its own is what keeps a fact carrying a number from having to be listed whole.
  if (value.includes(" · ")) return value.split(" · ").map(tdFact).join(" · ");
  return value;
}

function tdFact(value) {
  const translated = t(value);
  if (translated !== value) return translated;
  const parity = value.match(/^referans modelde (\d+) satırda karar eşleşmesi doğrulandı$/);
  if (parity) return `decision parity verified over ${parity[1]} rows on the reference model`;
  const hives = value.match(/^(\d+) kovan kendi profiliyle izleniyor$/);
  if (hives) return `${hives[1]} ${hives[1] === "1" ? "hive" : "hives"} monitored with their own profile`;
  const verified = value.match(/^(\d+)\/(\d+) kovan profili karar eşleşmesiyle doğrulandı$/);
  if (verified) return `${verified[1]}/${verified[2]} hive profiles verified by decision parity`;
  const missing = value.match(/^model dosyası bulunamadı: (.+)$/);
  if (missing) return `model file not found: ${missing[1]}`;
  return value;
}

function translatePage(root = document.body) {
  document.documentElement.lang = currentLanguage;
  // Everything inside [data-user-text] is something a person typed — a hive's name, an
  // apiary's location, an account's display name. This sweep translates every string it
  // walks past, and it could not tell those from interface copy: a colony actually called
  // "Bahçe Kovanı" was renamed to "Garden Hive" on the English panel, and any name that
  // happened to match a phrase in the table would have been rewritten the same way. A
  // record the panel silently renames is not the beekeeper's record any more.
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: node => node.parentElement && node.parentElement.closest("[data-user-text]")
      ? NodeFilter.FILTER_REJECT
      : NodeFilter.FILTER_ACCEPT,
  });
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
const colors = { normal: "#0b7a31", uyari: "#96600c", kritik: "#bd1f1e", veri_yok: "#646d7c" };
const hiveNames = { H1: "Bahçe Kovanı", H2: "Orman Kovanı", H3: "Çayır Kovanı" };

// A hive's name is something a beekeeper typed, not interface copy, so it is shown as
// written. It used to go through the translation table, which holds the three demo hives
// by name: a real colony called "Bahçe Kovanı" was renamed to "Garden Hive" on screen,
// and any hive whose name happened to collide with a UI string would have been rewritten
// too. The demo server keeps the translation, because there the names are part of the
// script rather than somebody's record of their own apiary.
function displayHiveName(name) { return demoAvailable ? t(name) : name; }
function displayHiveLocation(location) { return demoAvailable ? t(location) : location; }

function hiveLabel(hiveId) {
  return `${displayHiveName(hiveNames[hiveId]) || t("Kovan")} (${hiveId})`;
}

function hiveColor(hiveId) {
    // Chart lines are shapes, not words: they take the vivid family so several hives stay
  // apart at a glance, and each clears 3:1 against the page.
  const colors = ["#0f8a3c", "#b8760e", "#d02020", "#2563eb", "#7c3aed", "#0f766e"];
  const number = Number(hiveId.slice(1)) || 1;
  return colors[(number - 1) % colors.length];
}

function explainHiveIds(text) {
  return Object.keys(hiveNames).reduce(
    (result, hiveId) => result.replace(new RegExp(`\\b${hiveId}\\b`, "g"), hiveLabel(hiveId)),
    text
  );
}

// Turkish writes the sign in front of the number and English writes it after: %100
// against 100%. It was hard-coded in front everywhere but three report sentences, so an
// English panel read "%100 anomalous audio" on its own alarm cards.
function pct(value) {
  return currentLanguage === "en" ? `${value}%` : `%${value}`;
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

// One audio context for the whole session, opened on the first alarm and kept. Opening a
// new one per beep left every previous one running: browsers cap how many a page may hold,
// and the alarm tone is the last thing that should stop working after a long shift.
let alarmAudio = null;

function beep() {
  if (!soundEnabled) return;
  try {
    if (!alarmAudio) alarmAudio = new AudioContext();
    // A context created before the page was interacted with starts suspended.
    if (alarmAudio.state === "suspended") alarmAudio.resume();
    const oscillator = alarmAudio.createOscillator();
    const gain = alarmAudio.createGain();
    oscillator.frequency.value = 760;
    gain.gain.setValueAtTime(.12, alarmAudio.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, alarmAudio.currentTime + .45);
    oscillator.connect(gain).connect(alarmAudio.destination);
    oscillator.start(); oscillator.stop(alarmAudio.currentTime + .45);
    // The nodes are what accumulate once the context is shared; the context is not.
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
  } catch (error) {
    // A silent alarm is bad; a banner that fails to appear because the tone threw is worse.
    console.warn("Waggle: sesli uyarı çalınamadı", error);
  }
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
  // The three other confirmations on this panel are translated; this one, the only
  // irreversible one, asked in Turkish whatever language the screen was in.
  const confirmed = window.confirm(
    t("Bu işlem mevcut kovan, olay, alarm, rapor ve ayarları seçilen yedekle değiştirecek. Devam edilsin mi?")
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
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Günaydın" : hour < 18 ? "İyi günler" : "İyi akşamlar";
  document.querySelector("#greeting-text").textContent = t(greeting);
  document.querySelector("#greeting-name").textContent = currentDisplayName;
  latestEvents = data.events;
  reportEvents = [...new Map([...latestEvents, ...reportEvents].map(event => [event.id, event])).values()];
  latestHives = data.hives;
  data.hives.forEach(hive => { hiveNames[hive.hive_id] = hive.name; });
  if (latestReports.length) renderSelectedReport();
  const counts = data.hives.reduce((result, hive) => {
    result[hive.durum] = (result[hive.durum] || 0) + 1;
    return result;
  }, {});
  document.querySelector("#summary-total").textContent = data.hives.length;
  document.querySelector("#summary-normal").textContent = counts.normal || 0;
  document.querySelector("#summary-warning").textContent = counts.uyari || 0;
  document.querySelector("#summary-critical").textContent = counts.kritik || 0;
  const descriptions = {
    normal: t("Ses profili sağlıklı referans aralığında."),
    uyari: t("Değişimin kalıcılık süresi takip ediliyor."),
    kritik: t("Kalıcı değişim algılandı; fiziksel kontrol önerilir."),
    veri_yok: t("İlk akustik veri bekleniyor."),
  };
  hivesEl.innerHTML = data.hives.map(hive => `
    <article class="hive-list-row" style="--status:${colors[hive.durum]}">
      <div class="hive-list-name" data-user-text><strong>${escapeHtml(displayHiveName(hive.name))}</strong><small>${hive.hive_id}${hive.location ? ` · ${escapeHtml(displayHiveLocation(hive.location))}` : ""}</small></div>
      <span class="badge">${statusLabel(hive.durum)}</span>
      <span class="hive-list-description">${descriptions[hive.durum]}</span>
      <span class="hive-list-time">${dateLabel(hive.timestamp)}</span>
      <button class="hive-row-action" data-hive-detail="${hive.hive_id}" type="button" aria-label="${t("Detayları gör")}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 5.5 15.5 12 9 18.5"></path></svg></button>
    </article>`).join("");

  if (selectedHiveId) renderHiveDetail();
  updatedEl.textContent = `${t("Son güncelleme")} ${dateLabel(data.generated_at)}`;

  // An alarm someone has already inspected is not an alarm any more. The alarms page has
  // always counted only the open ones, so a closed alarm left the panel contradicting
  // itself: the overview announced a hive in trouble while the alarms page listed none.
  const critical = data.events.find(event => event.status === "ALARM" && !event.acknowledged_at);
  overviewAlert.hidden = !critical;
  if (critical) {
    overviewAlertTitle.textContent = currentLanguage === "en"
      ? `${hiveLabel(critical.hive_id)} needs attention`
      : `${hiveLabel(critical.hive_id)} dikkat istiyor`;
    overviewAlertCopy.textContent = t("Kalıcı akustik değişim algılandı. Fiziksel kontrol önerilir.");
  }
  const previousCriticalId = lastCriticalId;
  lastCriticalId = critical ? critical.id : null;
  // The first dashboard only records what was already open. An alarm raised before the
  // panel was opened is history, not news, and announcing it made every start of the app
  // sound like an emergency — with a toast and a sound for something the beekeeper may
  // have dealt with days ago. The banner still shows it; the toast and the beep are for
  // an alarm that arrives while someone is watching.
  if (critical && previousCriticalId !== undefined && critical.id !== previousCriticalId) {
    alertEl.textContent = currentLanguage === "en"
      ? `${hiveLabel(critical.hive_id)}: Persistent acoustic change — inspect the hive and verify the queen's condition`
      : `${hiveLabel(critical.hive_id)}: Kalıcı akustik değişim — kovanı ve kraliçeyi kontrol edin`;
    alertEl.classList.add("show"); beep();
    setTimeout(() => alertEl.classList.remove("show"), 5500);
  }
}

// A WATCH record is the moment the question "should I act?" is actually open, and the
// retrieved notes were reaching only ALARM cards. Any non-normal row can open the notes
// that fit it; the retriever needs no model, so this works with the local LLM switched off.
const expandedEventGuidance = new Set();

function renderEvents() {
  const filtered = latestEvents.filter(event =>
    (!selectedHiveId || event.hive_id === selectedHiveId) &&
    (eventFilter.value === "all" || event.status === eventFilter.value)
  );
  eventsEl.innerHTML = filtered.length ? filtered.map(event => {
    const acknowledge = event.status !== "ALARM" ? ""
      : event.acknowledged_at ? `<span class="acknowledged">${t("Kontrol edildi")}</span>`
      : `<button class="ack-button" data-ack="${event.id}" type="button">${t("Kontrol edildi olarak işaretle")}</button>`;
    const expanded = expandedEventGuidance.has(String(event.id));
    const guidance = event.status === "NORMAL" ? "" : `<button class="event-guidance-toggle" data-event-guidance="${event.id}" type="button" aria-expanded="${String(expanded)}">${t("Kılavuz")}</button>`;
    const actions = [acknowledge, guidance].filter(Boolean).join("") || "—";
    return `
    <tr><td>${dateLabel(event.timestamp)}</td><td>${hiveLabel(event.hive_id)}</td>
    <td class="${event.status === "ALARM" ? "event-critical" : ""}">${t(event.status === "ALARM" ? "Alarm" : event.status === "WATCH" ? "İzle" : "Normal")}</td>
    <td>${Math.round(event.anomaly_fraction * 100)}%</td>
    <td>${event.anomaly_severity == null ? "—" : Math.round(event.anomaly_severity * 100) + "%"}</td>
    <td>${actions}</td></tr>
    ${event.status === "NORMAL" ? "" : `<tr class="event-guidance-row" data-guidance-for="${event.id}"${expanded ? "" : " hidden"}><td colspan="6"><div class="event-guidance"></div></td></tr>`}`;
  }).join("") : `<tr><td colspan="6">${currentLanguage === "en" ? "No events match this filter." : "Filtreyle eşleşen olay yok."}</td></tr>`;
  expandedEventGuidance.forEach(eventId => fillEventGuidance(eventId));
}

async function fillEventGuidance(eventId) {
  const row = eventsEl.querySelector(`[data-guidance-for="${eventId}"]`);
  if (!row) return;
  const slot = row.querySelector(".event-guidance");
  const key = `${eventId}:${currentLanguage}`;
  let notes = alarmGuidanceCache.get(key);
  if (!notes) {
    slot.innerHTML = `<p class="alarm-guidance-label">${t("YEREL KILAVUZ")}</p>`;
    try {
      const response = await fetch(`/api/events/${encodeURIComponent(eventId)}/guidance?language=${currentLanguage}&limit=2`);
      if (!response.ok) return;
      notes = await response.json();
      alarmGuidanceCache.set(key, notes);
    } catch (error) {
      return;
    }
  }
  // A re-render while the request was in flight detaches the row it was meant for.
  if (!slot.isConnected) return;
  slot.innerHTML = notes.length
    ? `<p class="alarm-guidance-label">${t("YEREL KILAVUZ")}</p><ul>${notes.map(note =>
        // Same reasoning as the alarm card: the key is provenance, not field reading.
        `<li><span>${escapeHtml(note.text)}</span></li>`).join("")}</ul>`
    : `<p class="alarm-guidance-label">${t("Bu konuda not bulunamadı.")}</p>`;
}

function renderChart(events) {
  const svg = document.querySelector("#confidence-chart");
  const grid = [0, 25, 50, 75, 100].map(value => {
    const y = 195 - value * 1.7;
    return `<line class="grid-line" x1="45" y1="${y}" x2="885" y2="${y}"/><text class="axis-label" x="5" y="${y + 4}">${pct(value)}</text>`;
  }).join("");
  const hiveIds = selectedHiveId ? [selectedHiveId] : latestHives.map(hive => hive.hive_id);
  // The detail page chooses a period and a measurement; every other caller keeps the old
  // behaviour of drawing the last dozen anomaly fractions.
  const metric = selectedHiveId ? chartMetric() : "fraction";
  const field = metric === "severity" ? "anomaly_severity" : "anomaly_fraction";
  const series = hiveIds.map(hiveId => {
    const scoped = selectedHiveId ? eventsInRange(events, hiveId) : events.filter(event => event.hive_id === hiveId);
    // Severity is missing on records taken before the model reported it, and a gap is not
    // a zero: those points are left out rather than drawn on the floor.
    const values = scoped.filter(event => Number.isFinite(Number(event[field]))).slice(0, 40).reverse();
    if (!values.length) return "";
    const points = values.map((event, index) => {
      const x = values.length === 1 ? 465 : 55 + index * (820 / (values.length - 1));
      return { x, y: 195 - Number(event[field]) * 170 };
    });
    const color = hiveColor(hiveId);
    return `<polyline class="chart-line" stroke="${color}" points="${points.map(point => `${point.x},${point.y}`).join(" ")}"/>${points.map(point => `<circle class="chart-point" fill="${color}" cx="${point.x}" cy="${point.y}" r="6"/>`).join("")}`;
  }).join("");
  svg.innerHTML = grid + (series || `<text class="chart-empty" x="450" y="110">${t("Grafik için olay bekleniyor")}</text>`);
}

// How far back the chart looks, and which of the two measurements it draws. Both are
// read from the controls rather than held in their own variables so a re-render after a
// refresh cannot disagree with what the buttons show.
function chartRange() { return document.querySelector("#chart-range").dataset.value || "24h"; }
function chartMetric() { return document.querySelector("#chart-metric").dataset.value || "fraction"; }

const RANGE_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30};

function eventsInRange(events, hiveId) {
  const hours = RANGE_HOURS[chartRange()] || 24;
  const since = Date.now() - hours * 3600 * 1000;
  return events.filter(event => event.hive_id === hiveId && new Date(event.timestamp).getTime() >= since);
}

// The last event that carries a given field. A hive's newest record does not always hold
// every measurement — severity is absent on anything recorded before the model reported
// it — and showing "—" for a number that was measured an hour ago helps nobody.
function latestWith(events, hiveId, field) {
  return events.find(event => event.hive_id === hiveId && event[field] !== null && event[field] !== undefined);
}

function renderHiveDetail() {
  const hive = latestHives.find(item => item.hive_id === selectedHiveId);
  if (!hive) return;
  const hiveEvents = latestEvents.filter(event => event.hive_id === hive.hive_id);
  const openAlarm = hiveEvents.find(event => event.status === "ALARM" && !event.acknowledged_at);
  const severityEvent = latestWith(latestEvents, hive.hive_id, "anomaly_severity");
  const runEvent = latestWith(latestEvents, hive.hive_id, "consecutive_anomalies");

  document.querySelector("#detail-title").textContent = hiveLabel(hive.hive_id);
  const status = document.querySelector("#detail-status");
  status.textContent = statusLabel(hive.durum);
  status.style.setProperty("--status", colors[hive.durum]);

  document.querySelector("#detail-meta").innerHTML = [
    hive.location ? `<span>${escapeHtml(hive.location)}</span>` : "",
    `<span>${t("Son sinyal")}: ${dateLabel(hive.timestamp)}</span>`,
  ].filter(Boolean).join('<i aria-hidden="true">·</i>');

  // The inspection is offered where the alarm is being read, not only on the alarms page.
  document.querySelector("#detail-actions").innerHTML = openAlarm
    ? `<button class="alarm-primary-button" data-alarm-ack="${openAlarm.id}" type="button">${ICON_CLIPBOARD}${t("Fiziksel kontrolü başlat")}</button>`
    : "";

  const banner = document.querySelector("#detail-banner");
  banner.hidden = !openAlarm;
  if (openAlarm) {
    banner.innerHTML = `<span class="detail-banner-mark" aria-hidden="true">!</span>
      <div><strong>${t("Kalıcı akustik değişim sürüyor")}</strong><p>${escapeHtml(alarmSummary(openAlarm))}</p></div>
      <button class="alarm-secondary-link" data-open-alarms type="button">${t("Alarm kaydını incele")} <span aria-hidden="true">→</span></button>`;
  }

  const measured = value => value === null || value === undefined || !Number.isFinite(Number(value));
  document.querySelector("#detail-summary").innerHTML = `
    <article class="detail-tile"><span>${t("Güncel durum")}</span><strong style="color:${colors[hive.durum]}">${statusLabel(hive.durum)}</strong><small>${t(openAlarm ? "Acil kontrol önerilir" : "Kovanın son kaydına göre")}</small></article>
    <article class="detail-tile">${ICON_WAVE}<span>${t("Aykırı ses")}</span><strong>${measured(hive.anomaly_fraction) ? "—" : pct(Math.round(hive.anomaly_fraction * 100))}</strong><small>${t("Kaydın normal aralık dışında kalan bölümü")}</small></article>
    <article class="detail-tile">${ICON_SEVERITY}<span>${t("Sapma şiddeti")}</span><strong>${severityEvent ? pct(Math.round(severityEvent.anomaly_severity * 100)) : t("Ölçülmedi")}</strong><small>${t("Sesin normal profilden uzaklığı")}</small></article>
    <article class="detail-tile">${ICON_RUN}<span>${t("Kesintisiz değişim")}</span><strong>${runEvent ? `${runEvent.consecutive_anomalies} ${t("sn")}` : "—"}</strong><small>${t("Alarm eşiği 30 saniyedir")}</small></article>`;

  const drawn = eventsInRange(latestEvents, hive.hive_id);
  const metricLabel = chartMetric() === "severity" ? t("Sapma şiddeti") : t("Aykırı ses");
  document.querySelector("#chart-caption").textContent = drawn.length
    ? `${t(RANGE_CAPTION[chartRange()])} ${drawn.length} ${t("kayıt")} · ${metricLabel}`
    : t("Bu dönemde kayıt yok");
  document.querySelector("#chart-legend").innerHTML = `<span style="--dot:${hiveColor(hive.hive_id)}">${hiveLabel(hive.hive_id)}</span>`;
  renderChart(latestEvents);
  renderDetailPanels(hive, openAlarm, runEvent);
  renderEvents();
}

const RANGE_CAPTION = {"24h": "Son 24 saatte", "7d": "Son 7 günde", "30d": "Son 30 günde"};

// Two panels the page was missing: what to do about the state it is showing, and what
// produced that state. The steps are the same three the alarm card names, so a beekeeper
// reading either surface is told the same sequence.
function renderDetailPanels(hive, openAlarm, runEvent) {
  const steps = openAlarm
    ? ["Kovanı fiziksel olarak kontrol edin", "Kraliçe ve yavru düzenini doğrulayın", "Sonucu kaydedin"]
    : hive.durum === "uyari"
      ? ["Yeni bir ses kaydı alın", "Değişimin sürüp sürmediğine bakın", "Sürerse fiziksel kontrole geçin"]
      : ["Rutin akustik izlemeye devam edin", "Kayıtları benzer saatlerde alın", "Mikrofonun yerini değiştirmeyin"];
  document.querySelector("#detail-next-steps").innerHTML = `
    <div class="detail-panel-head"><span class="detail-panel-icon" aria-hidden="true">${ICON_GUIDANCE}</span><h3>${t("Bu durumda ne yapmalı?")}</h3></div>
    <ol class="detail-steps">${steps.map(step => `<li>${t(step)}</li>`).join("")}</ol>
    <button class="alarm-secondary-link" data-open-guidance type="button">${t("Yerel kılavuzu aç")} <span aria-hidden="true">→</span></button>`;

  const model = latestWith(latestEvents, hive.hive_id, "model");
  document.querySelector("#detail-monitoring").innerHTML = `
    <div class="detail-panel-head"><span class="detail-panel-icon" aria-hidden="true">${ICON_WAVE}</span><h3>${t("İzleme bilgisi")}</h3></div>
    <dl class="detail-facts">
      <div><dt>${t("Model")}</dt><dd>${model ? escapeHtml(model.model) : t("Kayıt yok")}</dd></div>
      <div><dt>${t("Sesli alarm")}</dt><dd>${t(soundEnabled ? "Açık" : "Kapalı")}</dd></div>
      <div><dt>${t("Kesintisiz değişim")}</dt><dd>${runEvent ? `${runEvent.consecutive_anomalies} / 30 ${t("sn")}` : "—"}</dd></div>
    </dl>`;
}

function updateNavIndicator(activeButton = document.querySelector(".nav-button.active")) {
  const navigation = document.querySelector(".main-nav");
  if (!navigation || !activeButton) {
    navigation?.style.setProperty("--indicator-opacity", "0");
    return;
  }
  const indicatorInset = Math.min(14, Math.max(9, activeButton.offsetWidth * 0.12));
  navigation.style.setProperty("--indicator-left", `${activeButton.offsetLeft + indicatorInset}px`);
  navigation.style.setProperty("--indicator-width", `${activeButton.offsetWidth - indicatorInset * 2}px`);
  navigation.style.setProperty("--indicator-opacity", "1");
}

function showView(viewName, moveFocus = false) {
  const activeView = document.querySelector(`#${viewName}-view`);
  let activeNavButton = null;
  document.querySelectorAll(".app-view").forEach(view => { view.hidden = view !== activeView; });
  document.querySelectorAll(".nav-button").forEach(button => {
    const active = button.dataset.view === viewName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
    if (active) activeNavButton = button;
  });
  updateNavIndicator(activeNavButton);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({top: 0, behavior: reduceMotion ? "auto" : "smooth"});
  queueHoverSync();
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
  if (viewName === "exports") refreshExports();
  if (viewName === "settings") {
    loadSettings();
    refreshRecoveryState();
    loadGuidanceNotes();
    if (managesAccounts && !workerPreview) refreshWorkers();
  }
  // Remember the section so a reload returns here instead of the overview. A hive detail
  // names the hive it is showing, because "#detail" on its own could not be restored — so
  // it used to leave the previous section in the address bar instead: opening a hive from
  // a report left the page reading "#reports", and reloading went back to the reports.
  const hash = viewName === "detail"
    ? (selectedHiveId ? `#hive/${selectedHiveId}` : location.hash)
    : `#${viewName}`;
  if (location.hash !== hash) history.replaceState(null, "", hash);
}

const NAV_VIEWS = ["overview", "hives", "alarms", "reports", "exports", "status", "settings"];

function restoreViewFromHash() {
  const requested = location.hash.replace("#", "");
  const hive = requested.startsWith("hive/") ? requested.slice(5) : "";
  // The same shape the API accepts, so a hand-edited address cannot put arbitrary text
  // through the renderer. An id no hive has simply renders nothing until one arrives.
  if (/^H[1-9][0-9]{0,2}$/.test(hive)) {
    selectedHiveId = hive;
    showView("detail");
    renderHiveDetail();
    return;
  }
  if (NAV_VIEWS.includes(requested) && requested !== "overview") showView(requested);
}

window.addEventListener("hashchange", restoreViewFromHash);

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

// One hive needs dozens of baseline recordings, so the queue is the normal case and a
// single file is just a queue of one. Everything below works on the queue.
function sensorQueueItems() {
  return sensorSource === "live" ? liveClips : [...sensorAudio.files].map(file => ({name: file.name, data: file}));
}

function renderSensorQueue() {
  const items = sensorQueueItems();
  const queue = document.querySelector("#sensor-queue");
  queue.hidden = items.length === 0;
  queue.innerHTML = items.map((item, index) => `
    <li>
      <span class="sensor-queue-index">${index + 1}</span>
      <span class="sensor-queue-name">${escapeHtml(item.name)}</span>
      ${item.seconds ? `<span class="sensor-queue-length">${formatClock(item.seconds)}</span>` : ""}
      ${sensorSource === "live" ? `<button class="sensor-queue-drop" data-drop-clip="${index}" type="button" aria-label="${t("Kaydı çıkar")}">×</button>` : ""}
    </li>`).join("");
  sensorButton.textContent = items.length > 1 ? `${items.length} ${t("kaydı gönder")}` : t("Kaydı gönder");
}

// The shared message style ships a green tick, so a failure printed through it reads as a
// success until you read the words. Errors have to say so in the styling too.
function setFormMessage(element, text, isError = false) {
  element.textContent = text;
  element.classList.toggle("is-error", Boolean(text) && isError);
}

function formatClock(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
}

// Anything that is not already WAV is decoded and re-encoded; the phone formats (m4a) and
// the live recorder's webm both arrive here.
async function toWav(item) {
  const alreadyWav = item.data.type === "audio/wav" || item.data.type === "audio/wave" || /\.wav$/i.test(item.name || "");
  if (alreadyWav) return {wav: item.data, context: null};
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error(t("Ses dosyası tarayıcı tarafından açılamadı."));
  const context = new AudioContextClass();
  const decoded = await context.decodeAudioData(await item.data.arrayBuffer());
  return {wav: encodeWav(decoded), context};
}

async function sendOneRecording(item) {
  const {wav, context} = await toWav(item);
  try {
    const params = new URLSearchParams({hive_id: managedHiveId, device_id: sensorDevice.value, filename: item.name || "phone-recording.wav"});
    // Training can take a while on the first run, but it must never hang silently:
    // without a deadline the button spins forever and the reason is invisible.
    const abort = new AbortController();
    const deadline = setTimeout(() => abort.abort(), 180000);
    let response;
    try {
      response = await fetch(`/api/sensor-recordings?${params}`, {
        method: "POST", headers: {"Content-Type": "audio/wav"}, body: wav, signal: abort.signal,
      });
    } catch (networkError) {
      throw new Error(abort.signal.aborted
        ? t("Sunucu üç dakika içinde yanıt vermedi. Sunucu günlüğünü kontrol edin.")
        : t("Sunucuya ulaşılamadı. Panel çalışıyor mu?"));
    } finally {
      clearTimeout(deadline);
    }
    const body = await response.json();
    if (!response.ok) {
      const failure = new Error(body.detail || t("Ses analizi başarısız oldu"));
      failure.status = response.status;
      throw failure;
    }
    return body;
  } finally {
    if (context) await context.close();
  }
}

async function analyzeSensorAudio() {
  const items = sensorQueueItems();
  if (!managedHiveId || !sensorDevice.value) { setFormMessage(sensorMessage, t("Önce bir cihaz ekleyin."), true); return; }
  if (!items.length) { setFormMessage(sensorMessage, t("Önce bir ses kaydedin veya dosya seçin."), true); return; }
  const analysedHiveId = managedHiveId;
  const batch = document.querySelector("#sensor-batch");
  const batchFill = document.querySelector("#sensor-batch-fill");
  const batchLabel = document.querySelector("#sensor-batch-label");
  sensorButton.disabled = true;
  sensorResult.hidden = true;
  batch.hidden = items.length < 2;
  const sent = [];
  const failed = [];
  let trained = null;
  let lastEvent = null;
  let lastBody = null;
  for (let index = 0; index < items.length; index += 1) {
    batchFill.style.width = `${Math.round(index / items.length * 100)}%`;
    batchLabel.textContent = `${index + 1}/${items.length}`;
    setFormMessage(sensorMessage, items.length > 1
      ? `${t("Kayıt gönderiliyor")} ${index + 1}/${items.length}: ${items[index].name}`
      : managedEnrollment?.can_monitor ? t("ONNX modeli analiz ediyor…") : t("Kayıt gönderiliyor ve profil çıkarılıyor…"));
    try {
      const body = await sendOneRecording(items[index]);
      sent.push(items[index].name);
      lastBody = body;
      if (body.event) lastEvent = body.event;
      if (body.model && !body.event) trained = body.model;
    } catch (error) {
      failed.push({name: items[index].name, reason: error.message});
      // A due health check rejects every remaining recording for the same reason, and a
      // dead server will not revive mid-batch. Stopping beats 40 identical failures.
      if (error.status === 422 || !error.status) break;
    }
  }
  batchFill.style.width = "100%";
  batchLabel.textContent = `${sent.length}/${items.length}`;

  if (!sent.length) {
    setFormMessage(sensorMessage, failed[0]?.reason || t("Ses analizi başarısız oldu"), true);
    sensorButton.disabled = false;
    return;
  }

  const enrollmentNote = trained
    ? t("Kovana özel profil doğrulandı ve izleme etkinleştirildi.")
    : t("Sağlıklı başlangıç kaydı eklendi. Profil hazır olana kadar alarm üretilmez.");
  const skipped = failed.length
    ? `<p class="sensor-result-failed">${failed.length} ${t("kayıt gönderilemedi")}: ${escapeHtml(failed[0].reason)}</p>`
    : "";
  sensorResult.innerHTML = lastEvent
    ? `<strong>${t("Analiz tamamlandı")}: ${t(lastEvent.status === "WATCH" ? "İzle" : lastEvent.status === "ALARM" ? "Alarm" : "Normal")}</strong><span>${t("Aykırı ses")}: ${pct(Math.round(lastEvent.anomaly_fraction * 100))}</span><span>${t("Pencere")}: ${lastBody.windows}</span><span>${t("Kaynak")}: ${escapeHtml(lastBody.model)}</span><p>${t("Yeni olay panele ve SQLite’a kaydedildi.")}</p>${skipped}`
    : `<strong>${sent.length} ${t("sağlıklı başlangıç kaydı")}</strong><span>${t("Pencere")}: ${lastBody.windows}</span><p>${enrollmentNote}</p>${skipped}`;
  sensorResult.dataset.status = lastEvent ? lastEvent.status.toLowerCase() : "enrollment";
  sensorResult.hidden = false;
  setFormMessage(sensorMessage, "");
  // `model` is only present when an upload completed training, which is the most
  // reliable signal we get; the snapshot comparison can miss it. A demo cannot reach
  // that point — the thresholds are weeks of recordings — so it plays the finish on
  // the first accepted recording instead.
  if (trained || demoMode) stageEnrollmentCompletion(analysedHiveId, managedEnrollmentByHive[analysedHiveId]?.progress_percent ?? 0);
  // The hive list keeps its own copy of the enrollment status, so it has to be refetched
  // too or the progress bar stays where it was until a reload. The progress these
  // recordings produced is up in the hive row, so reopening must not scroll back down.
  await Promise.all([refresh(), refreshAlarms(), refreshManagedHives(), openDevicePanel(analysedHiveId, {scroll: false})]);
  // Everything queued is sent; the panel has nothing more to show and only pushes the
  // hive row off screen. Recordings that failed stay queued so they can be retried.
  clearSensorQueue(failed.map(item => item.name));
  batch.hidden = true;
  sensorButton.disabled = false;
  if (failed.length) return;
  closeDevicePanel();
  const row = document.querySelector(`[data-hive-row="${analysedHiveId}"]`);
  if (row) {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    row.scrollIntoView({behavior: reduceMotion ? "auto" : "smooth", block: "center"});
    row.classList.add("is-highlighted");
    setTimeout(() => row.classList.remove("is-highlighted"), 2200);
  }
}

// Only what failed stays queued. Leaving the whole selection in place would re-send the
// recordings the server already accepted and double-count them into the profile.
function clearSensorQueue(keepNames = []) {
  liveClips = liveClips.filter(clip => keepNames.includes(clip.name));
  const kept = [...sensorAudio.files].filter(file => keepNames.includes(file.name));
  if (kept.length && window.DataTransfer) {
    const transfer = new DataTransfer();
    kept.forEach(file => transfer.items.add(file));
    sensorAudio.files = transfer.files;
  } else {
    sensorAudio.value = "";
  }
  renderSensorQueue();
}

// Recording in the browser needs a secure origin. That holds on the panel machine
// (127.0.0.1 counts as secure) but not over plain http on the LAN, which is exactly how
// the field phone connects — so the reason has to be said out loud, not swallowed.
function liveRecordingBlocker() {
  if (!window.isSecureContext) return t("Mikrofon yalnızca güvenli bağlantıda açılır. Bu cihazda paneli 127.0.0.1 üzerinden açın ya da telefonda kaydedip “Dosya yükle” sekmesinden gönderin.");
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return t("Bu tarayıcı mikrofon kaydını desteklemiyor. “Dosya yükle” sekmesini kullanın.");
  return null;
}

async function toggleLiveRecording() {
  const message = document.querySelector("#live-record-message");
  const toggle = document.querySelector("#live-record-toggle");
  if (mediaRecorder && mediaRecorder.state === "recording") { mediaRecorder.stop(); return; }
  const blocker = liveRecordingBlocker();
  if (blocker) { setFormMessage(message, blocker, true); return; }
  setFormMessage(message, "");
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
  } catch (error) {
    setFormMessage(message, t("Mikrofon izni verilmedi. Tarayıcı ayarlarından bu siteye mikrofon izni verin."), true);
    return;
  }
  const chunks = [];
  mediaRecorder = new MediaRecorder(stream);
  mediaRecorder.addEventListener("dataavailable", event => { if (event.data.size) chunks.push(event.data); });
  const startedAt = performance.now();
  mediaRecorder.addEventListener("stop", () => {
    const seconds = (performance.now() - startedAt) / 1000;
    stopLiveMeter(stream);
    toggle.classList.remove("recording");
    document.querySelector("#live-record-label").textContent = t("Dinlemeyi başlat");
    // Feature extraction works on one-second windows, so a blip carries no signal at all.
    if (seconds < 3) {
      setFormMessage(message, t("Kayıt çok kısa. En az 3 saniye dinletin."), true);
    } else {
      liveClipCounter += 1;
      liveClips.push({name: `canli-kayit-${liveClipCounter}.webm`, data: new Blob(chunks, {type: mediaRecorder.mimeType || "audio/webm"}), seconds});
      setFormMessage(message, `${t("Kayıt kuyruğa eklendi")} · ${formatClock(seconds)}`);
      renderSensorQueue();
    }
    mediaRecorder = null;
  });
  mediaRecorder.start();
  toggle.classList.add("recording");
  document.querySelector("#live-record-label").textContent = t("Dinlemeyi bitir");
  startLiveMeter(stream, startedAt);
}

function startLiveMeter(stream, startedAt) {
  const timer = document.querySelector("#live-record-timer");
  const fill = document.querySelector("#live-meter-fill");
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  liveMeter = {stream, context: null, frame: null, tick: null};
  // The elapsed time runs on a timer, not on animation frames: those stop while the tab
  // is in the background, and a recording that is still going must not read 00:00 when
  // the beekeeper comes back to it.
  const showElapsed = () => { timer.textContent = formatClock((performance.now() - startedAt) / 1000); };
  showElapsed();
  liveMeter.tick = setInterval(showElapsed, 250);
  // The level bar is purely visual, so animation frames are the right budget for it —
  // there is nothing to show while nobody is looking.
  if (AudioContextClass) {
    liveMeter.context = new AudioContextClass();
    const analyser = liveMeter.context.createAnalyser();
    analyser.fftSize = 1024;
    liveMeter.context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    const draw = () => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let index = 0; index < samples.length; index += 1) sum += samples[index] * samples[index];
      const level = Math.min(1, Math.sqrt(sum / samples.length) * 4.5);
      fill.style.width = `${Math.round(level * 100)}%`;
      liveMeter.frame = requestAnimationFrame(draw);
    };
    liveMeter.frame = requestAnimationFrame(draw);
  }
}

function stopLiveMeter(stream) {
  if (liveMeter?.frame) cancelAnimationFrame(liveMeter.frame);
  if (liveMeter?.tick) clearInterval(liveMeter.tick);
  if (liveMeter?.context) liveMeter.context.close();
  liveMeter = null;
  stream.getTracks().forEach(track => track.stop());
  document.querySelector("#live-meter-fill").style.width = "0%";
  document.querySelector("#live-record-timer").textContent = "00:00";
}

function selectSensorSource(source) {
  sensorSource = source;
  document.querySelectorAll("[data-sensor-source]").forEach(button => {
    const active = button.dataset.sensorSource === source;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  document.querySelector("#sensor-source-file").hidden = source !== "file";
  document.querySelector("#sensor-source-live").hidden = source !== "live";
  const message = document.querySelector("#live-record-message");
  if (source === "live") setFormMessage(message, liveRecordingBlocker() || "", true);
  renderSensorQueue();
}

// The settings page holds four unrelated jobs. They are shown one at a time and the
// sidebar carries what is true about each: how many guidance notes there are, whether the
// account still has no recovery code, which apiary these settings belong to.
function showSettingsTab(name) {
  document.querySelectorAll("[data-settings-tab]").forEach(button =>
    button.classList.toggle("is-active", button.dataset.settingsTab === name));
  document.querySelectorAll("[data-settings-panel]").forEach(panel => {
    panel.hidden = panel.dataset.settingsPanel !== name;
  });
}

function renderSettingsSidebar() {
  const apiary = document.querySelector("#settings-nav-apiary");
  if (!apiary) return;
  apiary.textContent = currentSettings?.location_name || currentSettings?.panel_name || "—";
  const hives = latestHives.length;
  document.querySelector("#settings-nav-hives").textContent = hives ? `${hives} ${t("kovan")}` : "";
  const count = document.querySelectorAll("#guidance-list li").length;
  document.querySelector("#settings-guidance-count").textContent = count ? `${count} ${t("not")}` : "";
  // Staff accounts exist only for the account that manages them; an empty tab would be a
  // door onto nothing.
  const team = document.querySelector("#settings-tab-team");
  if (team) team.hidden = !managesAccounts || workerPreview;
}

// A recovery code that was never generated is the one setting worth pointing at: without
// it a forgotten password is a command-line recovery. The badge is state, not decoration,
// so it disappears the moment a code exists.
function markSecurityRecommended(needed) {
  const badge = document.querySelector("#settings-security-badge");
  if (badge) badge.hidden = !needed;
}

function setSettingsState(state) {
  const line = document.querySelector("#settings-state");
  if (!line) return;
  line.className = `settings-state${state ? ` is-visible is-${state}` : ""}`;
  line.textContent = state === "dirty" ? t("Kaydedilmemiş değişiklikler var")
    : state === "saved" ? t("Tüm değişiklikler kaydedildi") : "";
}

function markSettingsSaved() { setSettingsState("saved"); }
function markSettingsDirty() { setSettingsState("dirty"); }

// Five fixed choices read faster as one row than as a menu that has to be opened. The
// select stays the source of truth so the form still submits and loads the same way.
function syncRefreshSegments() {
  const select = document.querySelector("#settings-refresh");
  const group = document.querySelector("#settings-refresh-segments");
  if (!select || !group) return;
  group.innerHTML = [...select.options].map(option =>
    `<button type="button" data-refresh="${escapeHtml(option.value)}"${option.value === select.value ? ' class="is-active"' : ""} aria-pressed="${option.value === select.value}">${escapeHtml(option.textContent)}</button>`).join("");
  group.querySelectorAll("[data-refresh]").forEach(button => button.addEventListener("click", () => {
    select.value = button.dataset.refresh;
    syncRefreshSegments();
    markSettingsDirty();
  }));
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
  document.querySelector("#settings-latitude").value = settings.latitude;
  document.querySelector("#settings-longitude").value = settings.longitude;
  document.querySelector("#settings-sound").checked = settings.sound_enabled;
  document.querySelector("#settings-weather").checked = settings.weather_enabled;
  document.querySelector("#settings-refresh").value = String(settings.refresh_seconds);
  document.querySelector("#settings-language").value = currentLanguage;
  syncRefreshSegments();
  // What is on screen is now what is stored, so the page says so and stops until the next
  // edit. Announcing "saved" while a field is still being typed into would be a lie.
  markSettingsSaved();
  renderSettingsSidebar();
  // The guide's progress is a single stored flag, not a per-step tally: the panel records
  // that it was finished, never how far through it someone got. Saying "4 of 6 done" would
  // be reporting a measurement nobody takes.
  const steps = document.querySelectorAll("#onboarding-dialog .onboarding-steps article").length;
  document.querySelector("#guide-state").textContent = settings.onboarding_completed
    ? `${steps} ${t("adım")} · ${t("tamamlandı")}`
    : `${steps} ${t("adım")} · ${t("henüz tamamlanmadı")}`;
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

// The guide shows one step at a time, so it has a cursor. Reopening it starts at the
// first step rather than resuming: the panel stores that the guide was finished, never
// how far through it someone got, and resuming from a position nobody recorded would be
// guessing.
let guideStep = 1;

function guideSteps() {
  return [...document.querySelectorAll("#onboarding-dialog .onboarding-steps article")];
}

function renderGuide() {
  const steps = guideSteps();
  const total = steps.length;
  guideStep = Math.min(Math.max(guideStep, 1), total);
  steps.forEach(step => { step.hidden = Number(step.dataset.step) !== guideStep; });
  document.querySelectorAll("#onboarding-rail li").forEach(item => {
    const index = Number(item.dataset.rail);
    item.toggleAttribute("data-done", index < guideStep);
    item.toggleAttribute("data-current", index === guideStep);
    // The connector arriving at a step is filled once the step it leaves has been reached,
    // so the rail reads as travel between two dots rather than as a fifth state.
    item.toggleAttribute("data-line", index - 1 <= guideStep);
  });
  document.querySelectorAll(".onboarding-orbit").forEach(orbit => {
    orbit.classList.toggle("is-active", Number(orbit.dataset.orbit) === guideStep);
  });
  document.querySelector("#guide-back").disabled = guideStep === 1;
  const label = document.querySelector("#guide-next-label");
  // Written in Turkish and handed to the translator, so switching language later still
  // finds a source string to translate rather than an already-translated one.
  label.textContent = guideStep === total ? "Anladım, panele geç" : "Devam et";
  translatePage(label);
}

function focusGuideStep() {
  const active = guideSteps().find(step => !step.hidden);
  const field = active?.querySelector("input");
  if (field) { field.focus(); return; }
  const heading = active?.querySelector("h3");
  if (!heading) return;
  heading.tabIndex = -1;
  heading.focus({preventScroll: true});
}

function openGuide() {
  const dialog = document.querySelector("#onboarding-dialog");
  guideStep = 1;
  renderGuide();
  if (!dialog.open) dialog.showModal();
}

function closeGuide() {
  document.querySelector("#onboarding-dialog").close();
}

function advanceGuide() {
  if (guideStep < guideSteps().length) {
    guideStep += 1;
    renderGuide();
    focusGuideStep();
    return;
  }
  completeGuide();
}

function retreatGuide() {
  if (guideStep === 1) return;
  guideStep -= 1;
  renderGuide();
  focusGuideStep();
}

// The first step asks for a hive name and location but does not create anything: the
// guide is a guide. What is typed is carried into the real hive form, where saving stays
// an explicit act, so the fields are neither dead nor quietly writing to the database.
function carryHiveDraft() {
  const nameField = document.querySelector("#guide-hive-name");
  const locationField = document.querySelector("#guide-hive-location");
  const name = nameField.value.trim();
  const location = locationField.value.trim();
  nameField.value = "";
  locationField.value = "";
  if (!name && !location) return;
  showView("hives", true);
  resetHiveForm();
  hiveForm.hidden = false;
  document.querySelector("#hive-name").value = name;
  document.querySelector("#hive-location").value = location;
  document.querySelector("#hive-name").focus();
}

function skipGuide() {
  closeGuide();
  carryHiveDraft();
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
  carryHiveDraft();
}

async function toggleLanguage() {
  if (!currentSettings) return;
  const language = currentLanguage === "tr" ? "en" : "tr";
  // The stored language belongs to the panel, and only the owner may write it. A field
  // worker pressing this got a 403 that was thrown away without a word, so the button did
  // nothing at all — the one control on the header that simply failed in silence. Reading
  // the panel in the other language costs the server nothing, so the refusal turns into a
  // local switch instead, remembered the same way the sign-in screen remembers it.
  const response = currentRole === "owner"
    ? await fetch("/api/settings", {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...currentSettings, language}),
      })
    : null;
  if (response && response.ok) {
    applySettings(await response.json());
  } else {
    localStorage.setItem("waggle-language", language);
    applySettings({...currentSettings, language});
  }
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
        // The place the weather is asked about, beside the name it is labelled with. The
        // two were allowed to drift: the name was editable here and the position was not.
        latitude: Number(form.latitude.value),
        longitude: Number(form.longitude.value),
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

// How late a component is, in the words a person uses. The page used to say "son olay
// beklenen süreden eski", which names neither the delay nor the expectation.
function lagLabel(component) {
  if (!component.last_seen_at) return "";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(component.last_seen_at).getTime()) / 1000));
  const minutes = Math.round(seconds / 60);
  const elapsed = minutes < 60
    ? `${minutes} ${t("dakika")}`
    : minutes < 1440 ? `${Math.round(minutes / 60)} ${t("saat")}` : `${Math.round(minutes / 1440)} ${t("gün")}`;
  if (component.status === "ok" || !component.stale_after_seconds) return `${t("Son veri")}: ${elapsed} ${t("önce")}`;
  const limit = Math.round(component.stale_after_seconds / 60);
  const expected = limit < 60 ? `${limit} ${t("dakika")}` : limit < 1440 ? `${Math.round(limit / 60)} ${t("saat")}` : `${Math.round(limit / 1440)} ${t("gün")}`;
  return `${elapsed} ${t("gecikti")} · ${t("beklenen aralık")} ${expected}`;
}

// A mark per stage of the chain. Drawn rather than lettered because the row is scanned,
// not read: the shape says which link of the chain this is before the label is reached.
const STAGE_MARKS = {
  device: '<path d="M5 10.5 12 6l7 4.5"></path><rect x="6" y="10.5" width="12" height="8" rx="1.4"></rect><path d="M9 14.5h6"></path><path d="M8.4 5.2a5 5 0 0 1 7.2 0M10.4 3.2a8 8 0 0 1 3.2 0"></path>',
  "acoustic-model": '<path d="M4 12h1.6M8 8.2v7.6M11.4 5.6v12.8M14.8 8.8v6.4M18.2 10.6v2.8M20.6 12H22"></path>',
  database: '<ellipse cx="12" cy="6.4" rx="6.6" ry="2.7"></ellipse><path d="M5.4 6.4v11.2c0 1.5 3 2.7 6.6 2.7s6.6-1.2 6.6-2.7V6.4"></path><path d="M5.4 12c0 1.5 3 2.7 6.6 2.7s6.6-1.2 6.6-2.7"></path>',
  reports: '<path d="M6.5 4h7l4 4v12h-11Z"></path><path d="M13.5 4v4h4"></path><path d="m10.5 12.6.9-2 .9 2 2 .9-2 .9-.9 2-.9-2-2-.9Z"></path>',
  panel: '<rect x="3.4" y="5" width="17.2" height="11.4" rx="1.8"></rect><path d="M9 20h6M12 16.4V20"></path><path d="M7.4 12.6v-2M10.6 12.6V9M13.8 12.6v-3.4M17 12.6V8"></path>',
};

function renderStatusChain(components) {
  const chain = document.querySelector("#status-chain");
  chain.innerHTML = components.map((component, index) => {
    // A stage that is not producing hands nothing on, so the break is drawn on its
    // outgoing link. Stages after it keep their own colour: a panel that is running is
    // running even when nothing is reaching it.
    const link = index < components.length - 1
      ? `<span class="status-link${component.status === "ok" ? "" : " is-broken"}" aria-hidden="true"><i></i></span>`
      : "";
    return `<li>
      <span class="status-stage ${component.status}" data-stage="${component.key}">
        <span class="status-stage-mark" aria-hidden="true"><svg viewBox="0 0 24 24">${STAGE_MARKS[component.key] || ""}</svg></span>
        <strong>${escapeHtml(td(component.name))}</strong>
        <span>${escapeHtml(td(component.summary))}</span>
      </span>${link}
    </li>`;
  }).join("");

  const counts = {ok: 0, waiting: 0, warning: 0};
  components.forEach(component => { counts[component.status] += 1; });
  const parts = [];
  if (counts.ok) parts.push(`<span><i class="ok"></i>${counts.ok} ${t("sağlıklı")}</span>`);
  if (counts.waiting) parts.push(`<span><i class="waiting"></i>${counts.waiting} ${t("veri bekliyor")}</span>`);
  if (counts.warning) parts.push(`<span><i class="warning"></i>${counts.warning} ${t("kontrol gerekli")}</span>`);
  // Worth saying on a page about connections: none of these checks leave the building.
  parts.push(`<span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.2 19 5.8v6.1c0 4-2.8 7.3-7 9-4.2-1.7-7-5-7-9V5.8Z"></path><path d="m9.2 11.9 2.2 2.2 3.6-4.1"></path></svg>${t("Kontroller yerel ağda çalışır")}</span>`);
  document.querySelector("#status-tally").innerHTML = parts.join("");
}

// The pointer is placed from the stage's own box rather than from a column count, so it
// stays on target when the labels change length or the row wraps to the narrow layout.
function anchorStatusDetails() {
  const field = document.querySelector("#status-chain");
  const detail = document.querySelector("#status-detail");
  if (!field || !detail) return;
  detail.querySelectorAll("[data-anchor]").forEach(card => {
    const stage = field.querySelector(`[data-stage="${card.dataset.anchor}"]`);
    if (!stage) return;
    const offset = stage.getBoundingClientRect().left + stage.getBoundingClientRect().width / 2
      - card.getBoundingClientRect().left;
    card.style.setProperty("--anchor", `${Math.round(offset)}px`);
  });
}

async function toggleContactHistory(button) {
  const card = button.closest(".status-detail-card");
  const existing = card.querySelector(".status-history, .status-history-empty");
  if (existing) {
    existing.remove();
    button.textContent = t("Bağlantı geçmişi");
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch(`/api/system-status/${button.dataset.history}/history?limit=12`);
    if (!response.ok) throw new Error(t("Bağlantı geçmişi alınamadı"));
    const entries = (await response.json()).entries || [];
    // "Cihaz verisi gecikiyor" is a claim about a pattern; an hour of silence after months
    // of hourly contact is a different problem from a device that was always sporadic.
    card.insertAdjacentHTML("beforeend", entries.length
      ? `<ul class="status-history">${entries.map(entry =>
          `<li><i class="${escapeHtml(entry.status)}"></i><time>${dateLabel(entry.at)}</time><span>${escapeHtml(td(entry.label))}</span></li>`).join("")}</ul>`
      : `<p class="status-history-empty">${t("Bu bileşenden henüz hiç kayıt ulaşmadı.")}</p>`);
    button.textContent = t("Geçmişi gizle");
  } catch (error) {
    card.insertAdjacentHTML("beforeend", `<p class="status-history-empty">${escapeHtml(error.message)}</p>`);
  } finally {
    button.disabled = false;
  }
}

// How late a component is, in the words a person uses. The page used to say "son olay
// beklenen süreden eski", which names neither the delay nor the expectation.
function lagLabel(component) {
  if (!component.last_seen_at) return "";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(component.last_seen_at).getTime()) / 1000));
  const minutes = Math.round(seconds / 60);
  const elapsed = minutes < 60
    ? `${minutes} ${t("dakika")}`
    : minutes < 1440 ? `${Math.round(minutes / 60)} ${t("saat")}` : `${Math.round(minutes / 1440)} ${t("gün")}`;
  if (component.status === "ok" || !component.stale_after_seconds) return `${t("Son veri")}: ${elapsed} ${t("önce")}`;
  const limit = Math.round(component.stale_after_seconds / 60);
  const expected = limit < 60 ? `${limit} ${t("dakika")}` : limit < 1440 ? `${Math.round(limit / 60)} ${t("saat")}` : `${Math.round(limit / 1440)} ${t("gün")}`;
  return `${elapsed} ${t("gecikti")} · ${t("beklenen aralık")} ${expected}`;
}

function renderSystemStatus(data) {
  const overview = document.querySelector("#status-overview");
  overview.className = `status-overview ${data.overall}`;
  overview.innerHTML = `<span class="status-pulse"></span><div><strong>${t(data.overall === "ok" ? "Tüm sistemler çalışıyor" : "Sistem çalışıyor, bazı bağlantılar veri bekliyor")}</strong><p>${t(data.overall === "ok" ? "Panel ve bütün entegrasyonlar güncel veri üretiyor." : "Bekleyen bileşenlerin ayrıntılarını aşağıda görebilirsiniz.")}</p></div>`;
  renderStatusChain(data.components);

  const statusLabels = {ok: "Çalışıyor", waiting: "Veri bekleniyor", warning: "Kontrol gerekli"};
  // Only what needs attention gets a card, hanging from the stage it is about. The healthy
  // stages have already said everything they have to say in the chain above.
  const needsAttention = data.components.filter(component => component.status !== "ok");
  document.querySelector("#status-detail").innerHTML = needsAttention.map(component => {
    const lag = lagLabel(component);
    const remedies = (component.remedies || []).length
      ? `<p class="status-remedy-title">${t("Sorun giderme adımları")}</p><ul class="status-remedies">${component.remedies.map(step => `<li>${escapeHtml(td(step))}</li>`).join("")}</ul>`
      : "";
    const history = component.has_history
      ? `<button class="status-history-toggle" type="button" data-history="${escapeHtml(component.key)}">${t("Bağlantı geçmişi")}</button>`
      : "";
    return `<article class="status-detail-card ${component.status}" data-anchor="${escapeHtml(component.key)}">
      <div class="status-detail-head"><h4>${escapeHtml(td(component.summary))}</h4><span class="status-detail-state">${t(statusLabels[component.status])}</span></div>
      <p>${escapeHtml(td(component.detail))}</p>
      ${lag ? `<span class="status-lag">${escapeHtml(lag)}</span>` : ""}
      ${component.last_seen_at ? `<small>${t("Son bağlantı")}: ${dateLabel(component.last_seen_at)}</small>` : ""}
      ${remedies}
      ${history}
    </article>`;
  }).join("");

  document.querySelector("#status-components").innerHTML = needsAttention.length ? "" :
    `<article class="status-all-clear"><span class="component-dot" aria-hidden="true" style="background:#1c8a5f;box-shadow:0 0 0 5px rgba(28,138,95,.12)"></span>
      <div><strong>${t("Zincirin tamamı çalışıyor")}</strong><p>${t("Kayıtlar mikrofondan panele kadar kesintisiz ulaşıyor; yapılacak bir şey yok.")}</p></div></article>`;

  document.querySelector("#status-detail").querySelectorAll("[data-history]")
    .forEach(button => button.addEventListener("click", () => toggleContactHistory(button)));
  anchorStatusDetails();

  document.querySelector("#status-updated").textContent = `${t("Son kontrol")}: ${dateLabel(data.generated_at)}`;
  const header = document.querySelector(".connection");
  header.classList.toggle("attention", data.overall !== "ok");
  header.querySelector(".connection-label").textContent = t(data.overall === "ok" ? "Sistem bağlı" : "Sistem çalışıyor");
}

window.addEventListener("resize", anchorStatusDetails);

// Written in Turkish and handed to the translator, so a later language switch still finds
// a source string on the button rather than an already-translated one.
function setStatusButtonLabel(button, turkish) {
  button.textContent = turkish;
  translatePage(button);
}

let statusCheckedTimer = 0;

async function refreshSystemStatus() {
  const button = document.querySelector("#refresh-status");
  // On a local panel the check answers in a few milliseconds, so a spinner is gone before
  // anyone sees it and the page it redraws usually looks identical to the one before —
  // which is why pressing this read as pressing nothing. The confirmation afterwards is
  // the part worth showing, so the button holds it long enough to be read.
  clearTimeout(statusCheckedTimer);
  button.classList.remove("is-done");
  button.disabled = true;
  setStatusButtonLabel(button, "Kontrol ediliyor…");
  try {
    const response = await fetch("/api/system-status");
    if (!response.ok) throw new Error(t("Sistem durumu alınamadı"));
    renderSystemStatus(await response.json());
    button.classList.add("is-done");
    setStatusButtonLabel(button, "Güncellendi");
    statusCheckedTimer = setTimeout(() => {
      button.classList.remove("is-done");
      setStatusButtonLabel(button, "Şimdi kontrol et");
    }, 2200);
  } catch (error) {
    setStatusButtonLabel(button, "Şimdi kontrol et");
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

// The learning period is the least obvious part of the product: a new hive collects a
// baseline for weeks and raises no alarm until it is done. The list has to say that.
// Plays the finish in two acts: the bar filling to 100, then the ready card. Both are
// real states the server passed through in one request; only the pacing is ours.
function stageEnrollmentCompletion(hiveId, fromPercent) {
  if (completingHives.has(hiveId) || justCompletedHives.has(hiveId) || (demoMode && demoCompletedHives.has(hiveId))) return;
  completingHives.set(hiveId, Math.max(0, Math.min(fromPercent ?? 0, 99)));
  renderManagedHives();
  setTimeout(() => {
    completingHives.delete(hiveId);
    justCompletedHives.add(hiveId);
    // In a demo the server is still at a handful of recordings, so letting the card
    // expire would drop the row back to "learning, 20%" right after showing it finish.
    if (demoMode) demoCompletedHives.add(hiveId);
    renderManagedHives();
    setTimeout(() => { justCompletedHives.delete(hiveId); renderManagedHives(); }, 9000);
  }, 7000);
}

// Demo-completed hives are presented as trained; the server still reports them enrolling.
function enrollmentSnapshot(hiveId) {
  const status = managedEnrollmentByHive[hiveId];
  if (!demoMode || !demoCompletedHives.has(hiveId)) return status;
  return {...(status || {}), state: "monitoring", progress_percent: 100, can_monitor: true, confirmation_due: false};
}

function enrollmentBlock(hive) {
  const status = enrollmentSnapshot(hive.hive_id);

  // The moment a profile finishes training is a real event, and it is the only part of
  // the learning period the beekeeper never gets to see. Hold it on screen briefly.
  // Training happens in the same request as the last recording, so the bar would jump
  // from its old value straight to the finished card. Play the fill first, then reveal.
  if (completingHives.has(hive.hive_id)) {
    const from = completingHives.get(hive.hive_id);
    return `
      <div class="enrollment-card training">
        <div class="enrollment-head">
          <div><strong>${t("Model eğitiliyor")}</strong><span>${t("Toplanan kayıtlardan kovana özel akustik profil çıkarılıyor.")}</span></div>
          <div class="enrollment-percent"><strong data-count-to="100" data-count-from="${from}">${pct(from)}</strong></div>
        </div>
        <div class="enrollment-track filling"><span style="--from:${from}%"></span></div>
      </div>`;
  }

  if (justCompletedHives.has(hive.hive_id)) {
    return `
      <div class="enrollment-card done">
        <div class="enrollment-head">
          <span class="enrollment-done-mark" aria-hidden="true"><svg viewBox="0 0 44 44"><circle cx="22" cy="22" r="19"></circle><path d="m13.5 22.5 6 6 11-12"></path></svg></span>
          <div><strong>${t("Profil hazır")}</strong><span>${t("Kovana özel akustik model eğitildi. Bu kovan artık izleniyor ve gerekirse alarm üretebilir.")}</span></div>
          <div class="enrollment-done-score"><strong>%100</strong><span>${t("tamamlandı")}</span></div>
        </div>
        <div class="enrollment-track done"><span style="width:100%"></span></div>
        <div class="enrollment-steps done">
          <span>${t("Kovana özel model")}</span>
          <span>${t("İzleme etkin")}</span>
          <span>${t("Gerekirse alarm")}</span>
        </div>
      </div>`;
  }

  if (!status || !hive.active || status.state === "monitoring" || status.state === "ready") return "";

  const waitingForDevice = status.state === "device_required";
  // Every threshold is met but the profile never activated: training ran and failed.
  // Saying "learning" at 100% hides a real fault behind a full bar.
  const stalled = !waitingForDevice && status.progress_percent >= 100 && !status.can_monitor;
  const blocked = !waitingForDevice && !stalled && status.confirmation_due;
  const tone = waitingForDevice ? "waiting" : stalled ? "stalled" : blocked ? "blocked" : "learning";
  const heading = waitingForDevice
    ? t("Cihaz bekleniyor")
    : stalled ? t("Profil eğitilemedi")
    : blocked ? t("Saha doğrulaması bekleniyor") : t("Kovanı öğreniyor");
  const note = waitingForDevice
    ? t("Öğrenme, kovana bir dinleme cihazı eklendiğinde başlar.")
    : stalled ? t("Eşikler doldu ancak model eğitimi tamamlanamadı. Birkaç kayıt daha gönderin; sorun sürerse sunucu günlüğüne bakın.")
    : blocked ? t("Kayıt toplamaya devam etmek için kovanı yerinde kontrol edip sonucu girin.")
    : t("Profil hazır olana kadar alarm üretilmez.");

  const steps = waitingForDevice ? "" : `
    <div class="enrollment-steps">
      <span><b>${status.recording_count}</b>/${status.required_recordings} ${t("kayıt")}</span>
      <span><b>${status.recording_days}</b>/${status.required_days} ${t("gün")}</span>
      <span><b>${status.confirmation_count}</b>/${status.required_confirmations} ${t("saha doğrulaması")}</span>
    </div>`;

  const action = waitingForDevice
    ? `<button class="enrollment-action" data-manage-device="${hive.hive_id}" type="button">${t("Cihaz ekle")}</button>`
    : `<button class="enrollment-action" data-manage-device="${hive.hive_id}" type="button">${t("Kayıt gönder")}</button>`;

  return `
    <div class="enrollment-card ${tone}">
      <div class="enrollment-head">
        <div><strong>${heading}</strong><span>${note}</span></div>
        <div class="enrollment-percent"><strong>${pct(status.progress_percent)}</strong>${action}</div>
      </div>
      <div class="enrollment-track"><span style="width:${Math.max(status.progress_percent, 2)}%"></span></div>
      ${steps}
    </div>`;
}

function renderManagedHives() {
  // The enrollment card needs its own full-width band in the row grid. Keying that off
  // "is the hive still learning" left the finished card stranded in the actions column,
  // so the layout follows whether a card was rendered at all.
  managedHives.innerHTML = managedHivesData.length ? managedHivesData.map((hive, index) => {
    const status = enrollmentSnapshot(hive.hive_id);
    const enrollment = enrollmentBlock(hive);
    return `
    <article class="managed-hive-row ${hive.active ? "" : "archived"}${enrollment ? " has-enrollment" : ""}" data-hive-row="${hive.hive_id}">
      <div class="managed-hive-identity"><span class="managed-hive-icon hive-tone-${index % 3}" aria-hidden="true"><svg viewBox="0 0 54 54"><path class="hive-roof" d="M15 17.5 21 11h12l6 6.5"></path><path class="hive-body" d="M14.5 18h25l3 6.5-2.7 6 1.5 6.5-4.8 6H17.5l-4.8-6 1.5-6.5-2.7-6 3-6.5Z"></path><path class="hive-band" d="M13 24.5h28M14.2 30.5h25.6M13.3 37h27.4"></path><path class="hive-feet" d="M18 43v3M36 43v3"></path><ellipse class="hive-door" cx="27" cy="38.5" rx="4.2" ry="4.8"></ellipse><path class="hive-bee-flight" d="M42 16c3-3 5 .4 2.7 2.3"></path><circle class="hive-bee-dot" cx="45.5" cy="14.5" r="1.4"></circle></svg></span><div data-user-text><strong>${escapeHtml(displayHiveName(hive.name))}</strong><span>${hive.location ? escapeHtml(displayHiveLocation(hive.location)) : t("Konum belirtilmedi")}</span></div></div>
      <div class="managed-hive-meta"><code>${hive.hive_id}</code><span class="managed-hive-state">${t(!hive.active ? "Arşivlendi" : status && !status.can_monitor ? "Öğrenme sürüyor" : "İzleme etkin")}</span></div>
      <div class="managed-hive-actions">
        ${hive.active ? `<button class="manage-device-button" data-manage-device="${hive.hive_id}" type="button"><svg aria-hidden="true" viewBox="0 0 20 20"><path d="M4 6.5h12M4 10h12M4 13.5h7M14 12l2 2-2 2"></path></svg>${t("Cihazlar ve model")}</button><button class="edit-hive-button" data-edit-hive="${hive.hive_id}" type="button"><svg aria-hidden="true" viewBox="0 0 20 20"><path d="m5 14.8.5-3.2 7.8-7.8 2.9 2.9-7.8 7.8-3.4.3Z"></path></svg>${t("Düzenle")}</button><button class="archive-button" data-archive-hive="${hive.hive_id}" type="button"><span class="archive-warning-dot" aria-hidden="true"></span>${t("Pasif hâle getir")}</button>` : `<button class="restore-hive-button" data-restore-hive="${hive.hive_id}" type="button">${t("Yeniden etkinleştir")}</button><button class="delete-hive-button" data-delete-hive="${hive.hive_id}" type="button"><svg aria-hidden="true" viewBox="0 0 20 20"><path d="M4 6h12M8 6V4.5h4V6M6 6l.8 9.5h6.4L14 6M8.5 9v4M11.5 9v4"></path></svg>${t("Kalıcı olarak sil")}</button>`}
      </div>
      ${enrollment}
    </article>`;
  }).join("") : `<p>${t("Henüz kovan eklenmedi.")}</p>`;
  startPercentCounters();
}

// Counts the label up alongside the bar so the number and the fill agree.
function startPercentCounters() {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  managedHives.querySelectorAll("[data-count-to]").forEach(element => {
    const from = Number(element.dataset.countFrom) || 0;
    const to = Number(element.dataset.countTo) || 100;
    if (reduceMotion || to <= from) { element.textContent = pct(to); return; }
    const started = performance.now();
    const duration = 6800;
    const step = now => {
      const ratio = Math.min((now - started) / duration, 1);
      const eased = 1 - Math.pow(1 - ratio, 3);
      element.textContent = pct(Math.round(from + (to - from) * eased));
      if (ratio < 1 && element.isConnected) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

// A local panel has no e-mail, so there is no reset link either: the current password is
// the only proof of ownership and the server always demands it.
async function changePassword(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#password-message");
  const current = document.querySelector("#current-password").value;
  const next = document.querySelector("#new-password").value;
  if (next !== document.querySelector("#new-password-confirm").value) {
    setFormMessage(message, t("Yeni parolalar eşleşmiyor"), true);
    return;
  }
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const response = await fetch("/api/password", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({current_password: current, new_password: next}),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || t("Parola değiştirilemedi"));
    }
    form.reset();
    setFormMessage(message, t("Parolanız değiştirildi. Bir sonraki girişte yeni parolayı kullanın."));
  } catch (error) {
    setFormMessage(message, error.message, true);
  } finally {
    button.disabled = false;
  }
}

// The rules are checked as you type so the server's refusal is never the first time you
// hear about them.
function renderPasswordRules() {
  const current = document.querySelector("#current-password").value;
  const next = document.querySelector("#new-password").value;
  const confirmation = document.querySelector("#new-password-confirm").value;
  const met = {
    length: next.length >= 10,
    match: Boolean(next) && next === confirmation,
    different: Boolean(next) && next !== current,
  };
  document.querySelectorAll("#password-rules li").forEach(item => {
    item.classList.toggle("met", met[item.dataset.rule]);
  });
}

async function refreshRecoveryState() {
  const state = document.querySelector("#recovery-state");
  const button = document.querySelector("#generate-recovery-code");
  try {
    const response = await fetch("/api/recovery-code");
    if (!response.ok) throw new Error(String(response.status));
    const status = await response.json();
    state.textContent = status.configured
      ? `${t("Kurtarma kodu tanımlı")} · ${dateLabel(status.created_at)}`
      : t("Bu hesapta henüz kurtarma kodu yok.");
    state.classList.toggle("configured", status.configured);
    button.textContent = status.configured ? t("Yeni kod üret") : t("Kurtarma kodu üret");
    markSecurityRecommended(!status.configured);
  } catch (error) {
    // 409 is the built-in demo account: it lives in the environment and has no database
    // row to keep a code in. Anything else is a failed request, and saying "this account
    // cannot have one" would send the reader looking for the wrong problem.
    const unsupported = error.message === "409";
    state.textContent = unsupported
      ? t("Bu hesap için kurtarma kodu tutulamıyor.")
      : t("Kurtarma kodu durumu okunamadı. Sayfayı yenileyin.");
    button.hidden = unsupported;
  }
}

async function generateRecoveryCode() {
  const message = document.querySelector("#recovery-message");
  const button = document.querySelector("#generate-recovery-code");
  // Generating replaces the old code, and the old one stops working immediately.
  if (document.querySelector("#recovery-state").classList.contains("configured")
      && !window.confirm(t("Yeni kod üretilirse eski kurtarma kodu geçersiz olur. Devam edilsin mi?"))) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/recovery-code", {method: "POST"});
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || t("Kurtarma kodu üretilemedi"));
    }
    const {code} = await response.json();
    document.querySelector("#recovery-code-value").textContent = code;
    document.querySelector("#recovery-code-box").hidden = false;
    setFormMessage(message, "");
    await refreshRecoveryState();
  } catch (error) {
    setFormMessage(message, error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function copyRecoveryCode() {
  const code = document.querySelector("#recovery-code-value").textContent;
  const message = document.querySelector("#recovery-message");
  try {
    await navigator.clipboard.writeText(code);
    setFormMessage(message, t("Kod panoya kopyalandı."));
  } catch (error) {
    setFormMessage(message, t("Kopyalanamadı; kodu elle not alın."), true);
  }
}

function printRecoveryCode() {
  const code = document.querySelector("#recovery-code-value").textContent;
  const sheet = window.open("", "_blank", "width=520,height=420");
  if (!sheet) {
    setFormMessage(document.querySelector("#recovery-message"), t("Yazdırma penceresi açılamadı."), true);
    return;
  }
  sheet.document.write(`<title>Waggle</title><body style="font:15px system-ui;padding:40px">
    <h1 style="font:600 22px Georgia,serif">Waggle ${t("kurtarma kodu")}</h1>
    <p>${escapeHtml(currentDisplayName || "")}</p>
    <p style="font:800 22px ui-monospace,monospace;letter-spacing:2px;margin:24px 0">${escapeHtml(code)}</p>
    <p style="color:#666">${t("Bu kod tek kullanımlıktır. Güvenli bir yerde saklayın.")}</p></body>`);
  sheet.document.close();
  sheet.print();
}

let workers = [];

async function refreshWorkers() {
  const response = await fetch("/api/users");
  if (!response.ok) return;
  workers = await response.json();
  renderWorkers();
}

function renderWorkers() {
  const list = document.querySelector("#worker-list");
  const team = workers.filter(user => user.role === "worker");
  if (!team.length) {
    list.innerHTML = `<p class="worker-empty">${t("Henüz çalışan hesabı yok.")}</p>`;
    return;
  }
  list.innerHTML = team.map(user => `
    <article class="worker-row${user.active ? "" : " inactive"}">
      <div class="worker-identity">
        <span class="worker-avatar" aria-hidden="true">${escapeHtml(user.display_name.trim().charAt(0).toUpperCase())}</span>
        <div><strong>${escapeHtml(user.display_name)}</strong><span>${escapeHtml(user.username)}</span></div>
      </div>
      <div class="worker-state">
        ${user.active ? `<span class="worker-badge active">${t("Etkin")}</span>` : `<span class="worker-badge">${t("Devre dışı")}</span>`}
        ${user.must_change_password ? `<span class="worker-badge pending">${t("Parolasını belirlemedi")}</span>` : ""}
      </div>
      <div class="worker-actions">
        <button data-worker-reset="${escapeHtml(user.username)}" type="button">${t("Parola ver")}</button>
        <button data-worker-active="${escapeHtml(user.username)}" data-active="${user.active}" type="button" class="${user.active ? "worker-disable" : ""}">${t(user.active ? "Devre dışı bırak" : "Yeniden etkinleştir")}</button>
      </div>
    </article>`).join("");
}

async function addWorker(event) {
  event.preventDefault();
  // `event.currentTarget` is null once the handler has awaited, so the form is captured
  // while the event is still being dispatched.
  const form = event.currentTarget;
  const message = document.querySelector("#worker-message");
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const response = await fetch("/api/users", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        display_name: document.querySelector("#worker-display-name").value.trim(),
        username: document.querySelector("#worker-username").value.trim(),
        password: document.querySelector("#worker-password").value,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || t("Çalışan eklenemedi"));
    }
    const created = await response.json();
    form.reset();
    form.hidden = true;
    setFormMessage(message, "");
    showReportNotice(`${created.display_name} ${t("eklendi. Geçici parolayı kendisine iletin.")}`);
    await refreshWorkers();
  } catch (error) {
    setFormMessage(message, error.message, true);
  } finally {
    button.disabled = false;
  }
}

// The owner types the replacement and reads it out — the offline equivalent of a reset
// link. It is temporary: the worker has to replace it before the account can act again.
async function resetWorkerPassword(username) {
  const password = window.prompt(`${username} ${t("için geçici parola (en az 10 karakter):")}`);
  if (password === null) return;
  const response = await fetch(`/api/users/${encodeURIComponent(username)}/password`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({password}),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showReportNotice(body.detail || t("Parola verilemedi"));
    return;
  }
  showReportNotice(t("Geçici parola verildi. Çalışan ilk girişinde kendi parolasını belirleyecek."));
  await refreshWorkers();
}

async function setWorkerActive(username, active) {
  if (!active && !window.confirm(`${username} ${t("devre dışı bırakılsın mı? Açık oturumu da hemen kapanır.")}`)) return;
  const response = await fetch(`/api/users/${encodeURIComponent(username)}`, {
    method: "PATCH", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({active}),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showReportNotice(body.detail || t("Değişiklik uygulanamadı"));
    return;
  }
  await refreshWorkers();
}

async function submitForcedPassword(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = document.querySelector("#force-password-message");
  const next = document.querySelector("#force-new-password").value;
  if (next !== document.querySelector("#force-new-password-confirm").value) {
    setFormMessage(message, t("Yeni parolalar eşleşmiyor"), true);
    return;
  }
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const response = await fetch("/api/password", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        current_password: document.querySelector("#force-current-password").value,
        new_password: next,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || t("Parola değiştirilemedi"));
    }
    document.querySelector("#force-password-dialog").close();
    form.reset();
    showReportNotice(t("Parolanız belirlendi. Artık kayıt gönderebilirsiniz."));
  } catch (error) {
    setFormMessage(message, error.message, true);
  } finally {
    button.disabled = false;
  }
}

const demoViewSwitch = document.querySelector("#demo-view-switch");

function renderDemoViewSwitch() {
  demoViewSwitch.classList.toggle("off", !demoMode);
  demoViewSwitch.setAttribute("aria-checked", String(demoMode));
  demoViewSwitch.querySelector(".demo-view-label").textContent = demoMode ? t("Demo görünümü") : t("Gerçek görünüm");
  demoViewSwitch.title = demoMode
    ? t("Profil tamamlanmış gibi gösteriliyor")
    : t("Sunucudaki gerçek öğrenme durumu");
}

// Separate from the demo switch: this previews the restricted panel a field worker gets.
// The owner keeps every power while previewing — it only changes what is on screen.
function setWorkerPreview(active) {
  workerPreview = active;
  document.body.classList.toggle("preview-as-worker", active);
  document.querySelector("#worker-preview-banner").hidden = !active;
  document.querySelector("#workers-section").hidden = !managesAccounts || active;
  renderSettingsSidebar();
  const button = document.querySelector("#preview-as-worker");
  if (button) button.textContent = active ? t("Önizlemeden çık") : t("Çalışan gözüyle bak");
}

// Both channels read the same server data; only the presentation differs. Nothing is
// written either way, so flipping back and forth mid-demo is free.
async function toggleDemoView() {
  if (!demoAvailable) return;
  demoMode = !demoMode;
  renderDemoViewSwitch();
  showReportNotice(demoMode
    ? t("Demo görünümü: profil tamamlanmış gibi gösteriliyor.")
    : t("Gerçek görünüm: sunucudaki asıl öğrenme durumu gösteriliyor."));
  renderManagedHives();
  if (managedHiveId) await openDevicePanel(managedHiveId, {scroll: false});
}

// The panel has done its job once the recording is on its way; fading it out reads as a
// finished step, where flipping `hidden` mid-scroll reads as the page glitching.
function closeDevicePanel() {
  const panel = document.querySelector("#hive-device-panel");
  managedHiveId = null;
  if (panel.hidden) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { panel.hidden = true; return; }
  panel.classList.add("is-closing");
  // `animationend` alone is not enough to rely on: CSS animations do not run while the
  // tab is in the background, and the panel would then stay open for good. The timeout
  // is the guarantee; the event just makes it feel immediate when the page is visible.
  let settled = false;
  const finish = () => {
    if (settled) return;
    settled = true;
    clearTimeout(fallback);
    panel.classList.remove("is-closing");
    panel.hidden = true;
  };
  const fallback = setTimeout(finish, 600);
  panel.addEventListener("animationend", finish, {once: true});
}

// Three separate thresholds gate the profile, and only one of them is about how many
// files you send. Hiding that behind a single percentage makes the flow look broken to
// anyone who uploads forty recordings in one afternoon and watches it stall at 43%.
function enrollmentRequirements(status) {
  const rows = [
    {done: status.recording_count >= status.required_recordings, label: t("Sağlıklı kayıt"), value: `${status.recording_count}/${status.required_recordings}`, note: t("Kovan sakinken alınmış kayıtlar. Tek seferde birden fazla dosya gönderebilirsiniz.")},
    {done: status.recording_days >= status.required_days, label: t("Farklı gün"), value: `${status.recording_days}/${status.required_days}`, note: t("Takvim günü sayılır: aynı gün kaç kayıt gönderirseniz gönderin 1 gün eklenir.")},
    {done: status.confirmation_count >= status.required_confirmations, label: t("Saha doğrulaması"), value: `${status.confirmation_count}/${status.required_confirmations}`, note: t("Kovanı yerinde kontrol edip sonucu girdiğinizde eklenir; en fazla dört günde bir istenir.")},
  ];
  return `
    <ul class="enrollment-requirements">
      ${rows.map(row => `
        <li class="${row.done ? "met" : ""}">
          <span class="requirement-mark" aria-hidden="true"></span>
          <div><strong>${row.label}</strong><span>${row.note}</span></div>
          <b>${row.value}</b>
        </li>`).join("")}
    </ul>
    <p>${t("Üç şart da dolmadan profil eğitilmez ve o zamana kadar hiç alarm üretilmez. Eksik kalırsa ilerleme olduğu yüzdede bekler, hiçbir şey kaybolmaz.")}</p>`;
}

async function openDevicePanel(hiveId, {scroll = true} = {}) {
  // Recordings belong to the hive they were queued for. Reopening the same hive keeps
  // them — that is how a failed upload gets retried — but switching hives must not carry
  // one hive's baseline audio into another's profile.
  if (managedHiveId !== hiveId) {
    liveClips = [];
    sensorAudio.value = "";
    selectSensorSource("file");
  }
  managedHiveId = hiveId;
  const hive = managedHivesData.find(item => item.hive_id === hiveId);
  const [devicesResponse, enrollmentResponse] = await Promise.all([
    fetch(`/api/hives/${hiveId}/devices`), fetch(`/api/hives/${hiveId}/enrollment`),
  ]);
  if (!devicesResponse.ok || !enrollmentResponse.ok) return;
  managedDevices = await devicesResponse.json();
  const enrollment = await enrollmentResponse.json();
  managedEnrollment = demoMode && demoCompletedHives.has(hiveId)
    ? {...enrollment, state: "monitoring", progress_percent: 100, can_monitor: true, confirmation_due: false}
    : enrollment;
  const panel = document.querySelector("#hive-device-panel");
  panel.classList.remove("is-closing");
  panel.hidden = false;
  document.querySelector("#device-panel-title").textContent = `${displayHiveName(hive?.name || hiveId)} · ${hiveId}`;
  const labels = {device_required: "Cihaz bekleniyor", enrolling: "Öğrenme devam ediyor", ready: "Profil hazır", monitoring: "İzleme etkin"};
  document.querySelector("#enrollment-status").innerHTML = `
    <div><strong>${t(labels[managedEnrollment.state])}</strong><span>${pct(managedEnrollment.progress_percent)}</span></div>
    <progress max="100" value="${managedEnrollment.progress_percent}"></progress>
    ${managedEnrollment.can_monitor
      ? `<p>${t("Bu kovanın profili hazır; yeni kayıtlar izleme ve alarm akışında değerlendirilir.")}</p>`
      : enrollmentRequirements(managedEnrollment)}`;
  sensorDevice.innerHTML = managedDevices.filter(device => device.active).map(device => `<option value="${device.device_id}">${escapeHtml(device.name)} · ${device.device_id}</option>`).join("");
  document.querySelector("#sensor-card").hidden = managedDevices.length === 0;
  document.querySelector("#health-confirmation-form").hidden = !managedEnrollment.confirmation_due;
  // One hive listens through one device, so the form has nothing left to do once a
  // device exists; leaving it open only invites a rejected second microphone.
  document.querySelector("#device-form").hidden = managedDevices.some(device => device.active);
  renderSensorQueue();
  if (scroll) panel.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
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
    const createdHiveId = editingHiveId ? null : hive.hive_id;
    message.textContent = successMessage;
    await refresh();
    await refreshManagedHives();
    // A hive without a device never starts learning, and nothing on screen said so.
    // Sending the user straight to the device step makes the two-part flow obvious.
    if (createdHiveId) {
      await openDevicePanel(createdHiveId);
      document.querySelector("#hive-device-panel").scrollIntoView({behavior: "smooth", block: "start"});
    }
  } catch (error) {
    message.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

async function refreshManagedHives() {
  const [response, enrollmentResponse] = await Promise.all([
    fetch("/api/hives?include_inactive=true"),
    fetch("/api/hives/enrollment?include_inactive=true"),
  ]);
  if (!response.ok) return;
  managedHivesData = await response.json();
  const previous = managedEnrollmentByHive;
  managedEnrollmentByHive = enrollmentResponse.ok ? await enrollmentResponse.json() : {};
  for (const [hiveId, status] of Object.entries(managedEnrollmentByHive)) {
    if (previous[hiveId] && !previous[hiveId].can_monitor && status.can_monitor) {
      stageEnrollmentCompletion(hiveId, previous[hiveId].progress_percent);
    }
  }
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

// A browser re-evaluates :hover only when the pointer next moves. A card that slides under
// a stationary cursor — the smooth scroll after a view switch, a refresh that changes the
// card's height — therefore stays unlit until the mouse twitches, which reads as "sometimes
// the hover just doesn't work". Tracking the pointer and re-checking after those moments
// closes the gap; the CSS :hover rule still does the work whenever the pointer does move.
const HOVER_SYNC_SELECTOR = ".weather-card";
let pointerPosition = null;
let hoverSyncFrame = null;

function syncPointerHover() {
  const under = pointerPosition
    ? document.elementFromPoint(pointerPosition.x, pointerPosition.y)
    : null;
  document.querySelectorAll(HOVER_SYNC_SELECTOR).forEach((element) => {
    element.classList.toggle("is-lit", Boolean(under) && element.contains(under));
  });
}

function queueHoverSync() {
  if (hoverSyncFrame) return;
  hoverSyncFrame = requestAnimationFrame(() => {
    hoverSyncFrame = null;
    syncPointerHover();
  });
}

document.addEventListener("pointermove", (event) => {
  pointerPosition = {x: event.clientX, y: event.clientY};
}, {passive: true});
document.addEventListener("pointerleave", () => {
  pointerPosition = null;
  syncPointerHover();
});
window.addEventListener("scroll", queueHoverSync, {passive: true});
// Measured: this browser keeps the hover state it had before a layout shift. An element the
// page pushes *under* a still cursor therefore never lights up, which is the intermittent
// part — it depends on whether the content above happened to finish loading first.
if (typeof ResizeObserver === "function") {
  new ResizeObserver(queueHoverSync).observe(document.body);
}

function renderWeather(weather) {
  document.querySelector("#weather-location").textContent = weather.location;
  document.querySelector("#weather-temp").textContent = `${Math.round(weather.temperature_c)}°`;
  document.querySelector("#weather-details").innerHTML = `<span>${t("Nem")} ${pct(weather.humidity_percent)}</span><span>${t("Rüzgâr")} ${Math.round(weather.wind_kmh)} km/h</span>`;
  queueHoverSync();
}

function renderWeatherDisabled() {
  document.querySelector("#weather-location").textContent = t("Çevrimiçi hava durumu kapalı");
  document.querySelector("#weather-temp").textContent = "—";
  document.querySelector("#weather-details").innerHTML = `<span>${t("Temel kovan izleme internet olmadan çalışmaya devam eder.")}</span>`;
  queueHoverSync();
}

function renderWeatherUnavailable() {
  document.querySelector("#weather-location").textContent = t("Hava durumu alınamadı");
  document.querySelector("#weather-temp").textContent = "—";
  document.querySelector("#weather-details").innerHTML = `<span>${t("Servise ulaşılamıyor. Kovan izleme bundan etkilenmez; kayıtlara hava bilgisi eklenmez.")}</span>`;
  queueHoverSync();
}

function reportTypeLabel(type) { return t(type === "event" ? "Olay" : type === "daily" ? "Günlük" : "Haftalık"); }

function filteredReportData() {
  const hive = document.querySelector("#report-hive-filter")?.value || "all";
  const start = document.querySelector("#report-date-start")?.value;
  const end = document.querySelector("#report-date-end")?.value;
  return allReports.filter(report => {
    if (activeReportType !== "all" && (report.report_type || "weekly") !== activeReportType) return false;
    if (hive !== "all" && !(report.hive_ids || []).includes(hive)) return false;
    if (start && new Date(report.period_end) < new Date(`${start}T00:00:00`)) return false;
    if (end && new Date(report.period_start) > new Date(`${end}T23:59:59`)) return false;
    return true;
  });
}

function renderReports(reports) {
  allReports = reports;
  const filtered = filteredReportData();
  const matching = filtered.filter(report => (report.language || "tr") === currentLanguage);
  latestReports = matching.length ? matching : filtered;
  const hiveFilter = document.querySelector("#report-hive-filter");
  const selectedHive = hiveFilter.value;
  const reportHiveIds = [...new Set(reports.flatMap(report => report.hive_ids || []))];
  hiveFilter.innerHTML = `<option value="all">${t("Tüm kovanlar")}</option>${reportHiveIds.map(id => `<option value="${id}">${escapeHtml(explainHiveIds(id))}</option>`).join("")}`;
  if ([...hiveFilter.options].some(option => option.value === selectedHive)) hiveFilter.value = selectedHive;
  const filterCount = document.querySelector("#report-filter-count");
  const isFiltered = activeReportType !== "all" || hiveFilter.value !== "all" || !!document.querySelector("#report-date-start").value || !!document.querySelector("#report-date-end").value;
  filterCount.textContent = isFiltered ? `${latestReports.length} ${t("rapor eşleşti")}` : "";
  reportSelect.innerHTML = latestReports.length ? latestReports.map(report => `<option value="${report.id}">${reportTypeLabel(report.report_type || "weekly")} · ${dateLabel(report.period_end)}</option>`).join("") : `<option value="">${t("Rapor yok")}</option>`;
  reportPickerMenu.innerHTML = latestReports.length ? latestReports.map(report => `<button data-report-id="${report.id}" type="button"><strong>${reportTypeLabel(report.report_type || "weekly")} · ${dateLabel(report.period_end)}</strong><span>${(report.hive_ids || []).map(explainHiveIds).join(", ")} · ${dateLabel(report.period_start)} – ${dateLabel(report.period_end)}</span></button>`).join("") : `<span class="report-picker-empty">${t("Rapor yok")}</span>`;
  renderSelectedReport();
}

function renderReportCharts(report) {
  const start = new Date(report.period_start), end = new Date(report.period_end);
  const events = reportEvents.filter(event => new Date(event.timestamp) >= start && new Date(event.timestamp) <= end && (report.hive_ids || []).includes(event.hive_id)).sort((a,b) => new Date(a.timestamp) - new Date(b.timestamp));
  const svg = document.querySelector("#report-trend-chart");
  const anomalyValues = events.map(event => Number(event.anomaly_fraction) || 0);
  const average = anomalyValues.length ? anomalyValues.reduce((sum,value) => sum + value,0) / anomalyValues.length : 0;
  const peak = anomalyValues.length ? Math.max(...anomalyValues) : 0;
  const alarmCount = events.filter(event => event.status === "ALARM").length;
  const alarmRate = events.length ? alarmCount / events.length : 0;
  document.querySelector("#report-event-count").textContent = events.length;
  document.querySelector("#report-average-anomaly").textContent = pct(Math.round(average * 100));
  document.querySelector("#report-peak-anomaly").textContent = pct(Math.round(peak * 100));
  document.querySelector("#report-alarm-rate").textContent = pct(Math.round(alarmRate * 100));

  if (!events.length) {
    svg.innerHTML = `<rect x="58" y="28" width="630" height="157" rx="10" fill="#fffaf1"/><text x="373" y="109" text-anchor="middle" fill="#8a8176" font-size="13">${t("Henüz olay yok.")}</text>`;
    document.querySelector("#report-trend-legend").innerHTML = "";
    document.querySelector("#report-trend-interpretation").textContent = currentLanguage === "en" ? "There are no acoustic records in this report period, so a direction of change cannot yet be calculated." : "Bu rapor döneminde akustik kayıt bulunmadığı için değişimin yönü henüz hesaplanamıyor.";
  } else {
    const palette = ["#c75f0c","#28786b","#bb3430","#7764a5","#5e7893"];
    const grouped = [...new Set(events.map(event => event.hive_id))].map((hiveId,index) => ({hiveId,color:palette[index%palette.length],events:events.filter(event => event.hive_id === hiveId)}));
    const firstTime = new Date(events[0].timestamp).getTime(), lastTime = new Date(events.at(-1).timestamp).getTime();
    const x = timestamp => 62 + ((new Date(timestamp).getTime()-firstTime) / Math.max(lastTime-firstTime,1)) * 626;
    const y = value => 185 - Math.max(0,Math.min(1,value)) * 157;
    const grid = [0,0.25,0.5,0.75,1].map(value => `<line x1="62" y1="${y(value)}" x2="688" y2="${y(value)}" stroke="${value === 0 ? "#cfc4b4" : "#eee4d5"}" stroke-width="1"/><text x="51" y="${y(value)+4}" text-anchor="end" fill="#7e756b" font-size="10" font-weight="700">${Math.round(value*100)}%</text>`).join("");
    const startLabel = new Date(events[0].timestamp).toLocaleDateString(currentLanguage === "en" ? "en-GB" : "tr-TR",{day:"2-digit",month:"short"});
    const endLabel = new Date(events.at(-1).timestamp).toLocaleDateString(currentLanguage === "en" ? "en-GB" : "tr-TR",{day:"2-digit",month:"short"});
    const series = grouped.map(group => { const points = group.events.map(event => `${x(event.timestamp)},${y(event.anomaly_fraction)}`).join(" "); return `<polyline points="${points}" fill="none" stroke="${group.color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>${group.events.map(event => `<circle cx="${x(event.timestamp)}" cy="${y(event.anomaly_fraction)}" r="4" fill="#fff" stroke="${group.color}" stroke-width="2"><title>${escapeHtml(explainHiveIds(group.hiveId))} · ${dateLabel(event.timestamp)} · ${Math.round(event.anomaly_fraction*100)}%</title></circle>`).join("")}`; }).join("");
    const averageY = y(average);
    const averageLabelAbove = averageY > 40;
    // The label was bare text drawn before the series, so any hive whose line ran near the
    // average was painted straight through the words. The dashes stay under the data — it
    // is a reference, not a reading — but the label rides on top, on its own chip.
    const averageText = currentLanguage === "en" ? `Average ${Math.round(average * 100)}%` : `Ortalama %${Math.round(average * 100)}`;
    const averageLabelWidth = averageText.length * 6.4 + 16;
    const averageLabelY = averageY + (averageLabelAbove ? -9 : 16);
    const averageDashes = `<line x1="62" y1="${averageY}" x2="688" y2="${averageY}" stroke="#c09256" stroke-width="1.5" stroke-dasharray="6 5"/>`;
    const averageLabel = `<rect x="${688 - averageLabelWidth}" y="${averageLabelY - 11}" width="${averageLabelWidth}" height="15" rx="7.5" fill="#fffdf9" stroke="#e6d3b0" stroke-width="1"/><text x="680" y="${averageLabelY}" text-anchor="end" fill="#96682d" font-size="10" font-weight="850">${averageText}</text>`;
    svg.innerHTML = `<rect x="58" y="23" width="634" height="168" rx="11" fill="#fffdf9"/>${grid}${averageDashes}${series}${averageLabel}<text x="62" y="211" fill="#756d64" font-size="10" font-weight="700">${startLabel}</text><text x="688" y="211" text-anchor="end" fill="#756d64" font-size="10" font-weight="700">${endLabel}</text><text x="375" y="229" text-anchor="middle" fill="#8a8176" font-size="10">${currentLanguage === "en" ? "Time" : "Zaman"}</text><text transform="rotate(-90 13 107)" x="13" y="107" text-anchor="middle" fill="#8a8176" font-size="10">${currentLanguage === "en" ? "Anomalous audio (%)" : "Aykırı ses (%)"}</text>`;
    document.querySelector("#report-trend-legend").innerHTML = grouped.map(group => {
      const share = group.events.reduce((sum, event) => sum + (Number(event.anomaly_fraction) || 0), 0) / group.events.length;
      return `<span class="chart-legend"><i style="background:${group.color}"></i>${escapeHtml(explainHiveIds(group.hiveId))}<b>${pct(Math.round(share * 100))}</b></span>`;
    }).join("");
    const peakEvent = events.reduce((best,event) => event.anomaly_fraction > best.anomaly_fraction ? event : best,events[0]);
    const movingGroups = grouped.filter(group => group.events.length > 1).map(group => group.events.at(-1).anomaly_fraction-group.events[0].anomaly_fraction);
    const rising = movingGroups.filter(delta => delta >= .08).length, falling = movingGroups.filter(delta => delta <= -.08).length;
    // "0 rose and 0 fell" is noise; when nothing moved, say so plainly.
    const steady = !rising && !falling;
    const directionText = currentLanguage === "en"
      ? (steady ? "No material change of direction was observed during the period." : `${rising} hive(s) increased and ${falling} hive(s) decreased materially.`)
      : (steady ? "Dönem boyunca belirgin bir yön değişimi görülmedi." : `${rising} kovanda belirgin artış, ${falling} kovanda belirgin azalış görüldü.`);
    document.querySelector("#report-trend-interpretation").textContent = currentLanguage === "en" ? `${directionText} The highest value was observed in ${explainHiveIds(peakEvent.hive_id)} (${Math.round(peak*100)}%); the overall average was ${Math.round(average*100)}%.` : `${directionText} En yüksek değer ${explainHiveIds(peakEvent.hive_id)} için %${Math.round(peak*100)}, tüm kayıtların ortalaması %${Math.round(average*100)} oldu.`;
  }
  const counts = ["NORMAL","WATCH","ALARM"].map(status => ({status,count:events.filter(event => event.status === status).length}));
  document.querySelector("#report-status-total").textContent = `${events.length} ${t("kayıt")}`;
  // One stacked bar reads the split at a glance; the rows below carry the exact numbers.
  document.querySelector("#report-status-bar").innerHTML = counts.filter(item => item.count).map(item =>
    `<span class="${item.status.toLowerCase()}" style="flex:${item.count}" title="${t(item.status === "WATCH" ? "İzle" : item.status === "ALARM" ? "Alarm" : "Normal")}: ${item.count}"></span>`
  ).join("") || `<span class="empty" style="flex:1"></span>`;
  document.querySelector("#report-status-chart").innerHTML = counts.map(item => { const percentage = events.length ? item.count/events.length*100 : 0; return `<div class="report-status-row ${item.status.toLowerCase()}${item.count ? "" : " is-empty"}"><div class="report-status-name"><i class="${item.status.toLowerCase()}"></i><span>${t(item.status === "WATCH" ? "İzle" : item.status === "ALARM" ? "Alarm" : "Normal")}</span></div><strong>${item.count}</strong><small>${pct(Math.round(percentage))}</small></div>`; }).join("");
  renderReportVerdict(report, events);
  const dominant = [...counts].sort((a,b) => b.count-a.count)[0];
  const dominantLabel = t(dominant.status === "WATCH" ? "İzle" : dominant.status === "ALARM" ? "Alarm" : "Normal");
  const leaders = counts.filter(item => item.count === dominant.count);
  document.querySelector("#report-status-interpretation").textContent = events.length ? (leaders.length > 1 ? (currentLanguage === "en" ? `The leading decision groups were evenly distributed. ${alarmCount} of ${events.length} records were ALARM (${Math.round(alarmRate*100)}%).` : `En yüksek sayıdaki karar grupları eşit dağıldı. ${events.length} kaydın ${alarmCount} tanesi ALARM oldu (%${Math.round(alarmRate*100)}).`) : (currentLanguage === "en" ? `${dominantLabel} was the most frequent decision. ${alarmCount} of ${events.length} records were classified as ALARM (${Math.round(alarmRate*100)}%).` : `En sık verilen karar ${dominantLabel} oldu. ${events.length} kaydın ${alarmCount} tanesi ALARM olarak sınıflandırıldı (%${Math.round(alarmRate*100)}).`)) : (currentLanguage === "en" ? "No decision distribution is available for this period." : "Bu dönem için karar dağılımı bulunmuyor.");
}

function renderReportVerdict(report, events) {
  const isEnglish = currentLanguage === "en";
  const states = (report.hive_ids || []).map(hiveId => {
    const hiveEvents = events.filter(event => event.hive_id === hiveId);
    // An alarm the beekeeper went out and found sound is answered, so the card stops
    // asking for it. It does not drop to "healthy" either: the sound did change, and the
    // report's own priority reads that period as one to watch. Confirmed, inconclusive
    // and uninspected alarms all stay urgent — the same rule the report applies.
    const outstanding = event => event.status === "ALARM" && event.inspection_result !== "no_issue_found";
    const state = hiveEvents.some(outstanding) ? "alarm"
      : hiveEvents.some(event => event.status === "WATCH" || event.status === "ALARM") ? "watch"
      : hiveEvents.length ? "normal" : "idle";
    return {hiveId, state, count: hiveEvents.length};
  });
  const countOf = state => states.filter(item => item.state === state).length;
  const alarmCount = countOf("alarm"), watchCount = countOf("watch");
  let tone = "idle", title = isEnglish ? "No records in this period" : "Bu dönemde kayıt bulunmuyor";
  if (alarmCount) { tone = "alarm"; title = isEnglish ? `${alarmCount} ${alarmCount > 1 ? "hives need" : "hive needs"} urgent inspection` : `${alarmCount} kovan acil kontrol istiyor`; }
  else if (watchCount) { tone = "watch"; title = isEnglish ? `${watchCount} ${watchCount > 1 ? "hives are" : "hive is"} under watch` : `${watchCount} kovan izlemede`; }
  else if (states.some(item => item.state === "normal")) { tone = "normal"; title = isEnglish ? "All hives look healthy" : "Tüm kovanlar sağlıklı görünüyor"; }
  const verdict = document.querySelector("#report-verdict");
  verdict.className = `report-verdict ${tone}`;
  document.querySelector("#report-verdict-title").textContent = title;
  document.querySelector("#report-verdict-note").textContent = isEnglish ? `Based on ${events.length} acoustic records in the report period` : `Rapor dönemindeki ${events.length} akustik kayda göre`;
  // The banner used to be a sentence with 400px of empty space beside it. The hive it is
  // talking about is known here, so the banner can be the way to it.
  const attention = states.find(item => item.state === "alarm") || states.find(item => item.state === "watch");
  document.querySelector("#report-verdict-action").innerHTML = attention
    ? `<button class="report-verdict-open" data-hive-detail="${escapeHtml(attention.hiveId)}" type="button"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.2 19.5 6v6.4c0 4.2-3 7.6-7.5 9.4-4.5-1.8-7.5-5.2-7.5-9.4V6Z"/><path d="m8.8 12.2 2.4 2.4 4.2-4.6"/></svg>${isEnglish ? "Inspect the hive" : "Kovanı kontrol et"}</button>`
    : "";
  const stateLabels = {
    alarm: isEnglish ? "Urgent check" : "Acil kontrol",
    watch: isEnglish ? "Under watch" : "İzlemede",
    normal: isEnglish ? "Steady" : "Düzenli",
    idle: isEnglish ? "No records" : "Kayıt yok"
  };
    // The glyph sits with the hive name, not beside the verdict: at three columns the card
  // is 178px inside, and taking 56px of that made "Urgent check" wrap onto two lines.
  document.querySelector("#report-hive-states").innerHTML = states.map(item => `<article class="report-hive-state ${item.state}"><span class="report-hive-state-name">${REPORT_HIVE_GLYPH}${escapeHtml(explainHiveIds(item.hiveId))}</span><strong>${stateLabels[item.state]}</strong><small>${item.count} ${isEnglish ? "records" : "kayıt"}</small></article>`).join("");
  renderReportActions(report, states, isEnglish);
}

// One hive glyph tinted by state, rather than an icon guessed from the hive's name — a
// hive called "Dedemin kovanı" has no forest or flower to draw.
const REPORT_HIVE_GLYPH = `<span class="report-hive-glyph" aria-hidden="true"><svg viewBox="0 0 40 40"><path class="glyph-frame" d="M20 3.5 33 11v18L20 36.5 7 29V11Z"/><path class="glyph-hive" d="M13.5 17 20 12.3 26.5 17M12.6 17h14.8M12 21.4h16M12.6 25.8h14.8M13.2 25.8 14 29.4h12l.8-3.6"/><ellipse class="glyph-door" cx="20" cy="26" rx="2.2" ry="2.6"/></svg></span>`;

const ACTION_TAG_ICONS = {
  alarm: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.4"/><path d="M12 7.8v5M12 16.1v.1"/></svg>`,
  watch: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.9 12S6.6 7 12 7s9.1 5 9.1 5-3.7 5-9.1 5-9.1-5-9.1-5Z"/><circle cx="12" cy="12" r="2.3"/></svg>`,
  normal: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.4"/><path d="m8.4 12.3 2.6 2.6 4.6-5.2"/></svg>`,
};
ACTION_TAG_ICONS.idle = ACTION_TAG_ICONS.normal;

// The guidance base is what makes "grounded in reviewed local notes" checkable rather
// than a claim. All 28 are browsable here; a report shows only the handful it used.
let guidanceNotes = [];

async function loadGuidanceNotes() {
  try {
    guidanceNotes = await fetch(`/api/guidance?language=${currentLanguage}`).then(response => response.json());
  } catch (error) {
    guidanceNotes = [];
  }
  renderGuidanceNotes();
  renderSettingsSidebar();
}

// Searching the base runs the same retriever a report is grounded with, rather than a
// substring match. The one screen where a person can inspect the knowledge base should
// rank passages the way the retrieval it exists to explain ranks them.
let guidanceSearchToken = 0;

// The citation a report follows back into the base. Printed under the note rather than as
// its heading — and not at all when it is the only name the note has, because the same
// slug twice tells a reader nothing the first one did not.
function sourceLine(note) {
  if (!note.title || note.title === note.id) return "";
  return `<span class="guidance-source">${escapeHtml(note.id)}</span>`;
}

async function renderGuidanceNotes() {
  const query = document.querySelector("#guidance-search").value.trim();
  let matching = guidanceNotes;
  if (query) {
    const token = ++guidanceSearchToken;
    try {
      const found = await fetch(`/api/guidance?language=${currentLanguage}&q=${encodeURIComponent(query)}&limit=10`)
        .then(response => response.json());
      // A slower earlier request must not overwrite the answer to what is typed now.
      if (token !== guidanceSearchToken) return;
      matching = found;
    } catch (error) {
      if (token !== guidanceSearchToken) return;
      matching = [];
    }
  }
  document.querySelector("#guidance-count").textContent = query
    ? `${matching.length}/${guidanceNotes.length} ${t("not")}`
    : `${guidanceNotes.length} ${t("not")}`;
  // A note is named and filed under a subject a beekeeper recognises. The tags underneath
  // were the retriever's own vocabulary — "consecutive_anomalies", "false_positive" — and
  // printing them here showed the reader the machine's index instead of their own topic.
  // The id stays, small and last, because a report cites it and that trail has to hold.
  document.querySelector("#guidance-list").innerHTML = matching.length
    ? matching.map(note => `
      <li>
        <div class="guidance-note-head"><strong>${escapeHtml(note.title || note.id)}</strong>
        <span class="guidance-category">${escapeHtml(note.category || "")}</span></div>
        <p>${escapeHtml(note.text)}</p>
        ${sourceLine(note)}
      </li>`).join("")
    : `<li class="guidance-empty"><p>${t("Bu konuda not bulunamadı.")}</p></li>`;
}

// The model's structured decision used to be computed, validated and then dropped: only
// the grounding ids ever reached the panel. This shows what it actually concluded.
const DECISION_PRIORITIES = {routine: "Rutin", watch: "İzleme", immediate: "Acil"};
const DECISION_PATTERNS = {
  within_baseline: "Normal aralıkta",
  developing_acoustic_change: "Gelişen akustik değişim",
  persistent_acoustic_change: "Kalıcı akustik değişim",
};
const DECISION_ACTIONS = {
  continue_monitoring: "İzlemeye devam",
  record_again: "Kaydı tekrarla",
  inspect_hive: "Kovanı fiziksel kontrol et",
  check_queen: "Kraliçeyi doğrula",
};

function renderModelDecision(assessment) {
  const card = document.querySelector("#report-decision");
  if (!assessment || !assessment.priority) { card.hidden = true; return; }
  const priority = document.querySelector("#report-decision-priority");
  priority.textContent = t(DECISION_PRIORITIES[assessment.priority] || assessment.priority);
  priority.className = `report-decision-priority ${assessment.priority}`;
  document.querySelector("#report-decision-pattern").textContent =
    t(DECISION_PATTERNS[assessment.pattern] || assessment.pattern || "—");
  // "Compatible with" is not "caused by", and the wording has to keep saying so.
  document.querySelector("#report-decision-queen").textContent =
    assessment.queen_loss_compatible ? t("Uyumlu olabilir, kesin tanı değil") : t("Uyumlu değil");
  document.querySelector("#report-decision-inspection").textContent =
    assessment.inspection_required ? t("Gerekli") : t("Şu an gerekmiyor");
  const actions = (assessment.action_codes || []).map(code => t(DECISION_ACTIONS[code] || code));
  document.querySelector("#report-decision-actions").textContent = actions.length ? actions.join(" · ") : "—";
  card.hidden = false;
}

// A source count is a claim; the passages themselves are the evidence. A report stores
// only their ids, so the texts are fetched and shown beside the assessment they shaped.
let guidanceCache = null;

async function renderReportSources(ids) {
  const card = document.querySelector("#report-sources-card");
  if (!ids || !ids.length) { card.hidden = true; return; }
  try {
    if (!guidanceCache || guidanceCache.language !== currentLanguage) {
      const notes = await fetch(`/api/guidance?language=${currentLanguage}`).then(response => response.json());
      guidanceCache = {language: currentLanguage, byId: new Map(notes.map(note => [note.id, note]))};
    }
    const found = ids.map(id => guidanceCache.byId.get(id)).filter(Boolean);
    if (!found.length) { card.hidden = true; return; }
    // The same treatment as the guidance base: the note's name leads, its id follows for
    // the audit trail. A list of slugs said what the retriever matched, not what it said.
    document.querySelector("#report-sources-list").innerHTML = found.map(note => `
      <li>
        <div class="guidance-note-head"><strong>${escapeHtml(note.title || note.id)}</strong>
        ${note.category ? `<span class="guidance-category">${escapeHtml(note.category)}</span>` : ""}</div>
        <p>${escapeHtml(note.text)}</p>
        ${sourceLine(note)}
      </li>`).join("");
    card.hidden = false;
  } catch (error) {
    card.hidden = true;
  }
}

function renderReportActions(report, states, isEnglish) {
  const stateByHive = new Map(states.map(item => [item.hiveId, item.state]));
  const tags = {
    alarm: isEnglish ? "URGENT · TODAY" : "ACİL · BUGÜN",
    watch: isEnglish ? "WATCH" : "İZLEME",
    normal: isEnglish ? "ROUTINE" : "RUTİN",
    idle: isEnglish ? "ROUTINE" : "RUTİN"
  };
  const openLabel = isEnglish ? "Open hive" : "Kovanı aç";
  document.querySelector("#report-actions").innerHTML = (report.recommendations || []).map(item => {
    const hiveId = (report.hive_ids || []).find(id => new RegExp(`(^|[^A-Za-z0-9])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^A-Za-z0-9]|$)`).test(item));
    const state = (hiveId && stateByHive.get(hiveId)) || "normal";
    const action = hiveId ? `<button class="report-action-open" data-hive-detail="${escapeHtml(hiveId)}" type="button">${openLabel}</button>` : "";
    // Priority sits to the right as a chip rather than stacked over the sentence: the row
    // then reads number → what to do → how urgent, on one line, and fills the space the
    // "open hive" button leaves empty on most recommendations.
    return `<li class="${state}"><p>${escapeHtml(explainHiveIds(item))}</p><span class="report-action-tag">${ACTION_TAG_ICONS[state]}${tags[state]}</span>${action}</li>`;
  }).join("");
}

function renderSelectedReport() {
  const report = latestReports.find(item => String(item.id) === reportSelect.value) || latestReports[0];
  if (!report) {
    document.querySelector("#report-period").textContent = "—";
    document.querySelector("#report-picker-kind").textContent = t("Rapor yok");
    return;
  }
  reportSelect.value = String(report.id);
  const selectedIndex = latestReports.findIndex(item => item.id === report.id);
  const locale = currentLanguage === "tr" ? "tr-TR" : "en-GB";
  const startDate = new Date(report.period_start), endDate = new Date(report.period_end);
  const monthDay = value => new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(value);
  const rangeYear = endDate.getFullYear();
  const clockTime = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(endDate);
  // A shared month collapses to "24 – 31 Ağu 2026" so the range stays on one line.
  const sameMonth = startDate.getFullYear() === rangeYear && startDate.getMonth() === endDate.getMonth();
  const range = sameMonth
    ? `${startDate.getDate()} – ${monthDay(endDate)} ${rangeYear}`
    : `${monthDay(startDate)} – ${monthDay(endDate)} ${rangeYear}`;
  document.querySelector("#report-period").textContent = range;
  document.querySelector("#report-picker-kind").textContent = `${reportTypeLabel(report.report_type || "weekly")} · ${clockTime}`;
  document.querySelector("#report-summary-title").textContent = t((report.report_type || "weekly") === "event" ? "Olay özeti" : report.report_type === "daily" ? "Günün özeti" : "Haftanın özeti");
  const generator = report.generator || "manual";
  const isAgent = generator.toLowerCase().includes("agent");
  const isFoundry = generator.toLowerCase().includes("foundry") || isAgent;
  const isDeterministicDemo = generator.toLowerCase() === "deterministic-demo";
  const isSafeFallback = generator.toLowerCase() === "safe-fallback";
  document.querySelector("#report-source").textContent = isAgent ? "Agent Framework + Foundry Local" : isFoundry ? "Foundry Local · Phi" : isSafeFallback ? t("Deterministik yedek motor") : isDeterministicDemo ? t("Waggle Yerel Rapor Motoru") : generator;
  // A second local model checked the priority. Whether the two agreed is part of how much
  // the reader should trust the number, so it is said rather than left in a log file.
  // It is read from the stored assessment, which is where the validator actually recorded
  // it and where the PDF already reads it from. Sniffing the generator string for a "+"
  // claimed a cross-check on every report that merely had model-written prose, because
  // that suffix is "+llm-narrative"; reports written before the assessment column existed
  // still fall back to the string, with that suffix removed first.
  const crossCheckModel = report.assessment?.cross_check_model || null;
  const legacyGenerator = generator.replace(/\+llm-narrative/gi, "");
  const crossChecked = crossCheckModel ? true : (!report.assessment && legacyGenerator.includes("+"));
  const disagreed = crossCheckModel
    ? report.assessment.cross_check_agreed === false
    : (!report.assessment && legacyGenerator.includes("(disagreed)"));
  // Saying nothing here leaves two very different situations looking identical: no second
  // model configured, and a second model whose answer was rejected. Only a model-produced
  // report can be cross-checked at all, so the single-model line is limited to those.
  document.querySelector("#report-cross-check").textContent =
    disagreed ? t("İki yerel model farklı karar verdi; temkinli olan seçildi.")
    : crossChecked ? t("İki yerel model aynı kararda birleşti.")
    : (isFoundry || isAgent) ? t("Tek yerel modelin kararı; çapraz doğrulama yapılmadı.")
    : "";
  document.querySelector("#report-cross-check").className =
    `report-cross-check${disagreed ? " disagreed" : crossChecked ? " agreed" : (isFoundry || isAgent) ? " single" : ""}`;
  const groundingSources = report.grounding_sources || [];
  document.querySelector("#report-provenance").textContent = [isSafeFallback ? t("Yapay zekâ modeline ulaşılamadı") : "", groundingSources.length ? t("RAG ile kaynaklandırıldı") : "", isAgent ? t("Agent tarafından hazırlandı") : ""].filter(Boolean).join(" · ");
  document.querySelector(".report-aside-meta").classList.toggle("is-degraded", isSafeFallback);
  const modelBacked = isFoundry || isAgent;
  const modelWroteText = generator.toLowerCase().includes("llm-narrative");
  document.querySelector("#report-processing-note").textContent = modelWroteText ? t("Metni model yazdı") : modelBacked ? t("Yerel modelle") : t("Yerelde işlendi");
  document.querySelector("#report-grounding-note").hidden = !modelBacked;
  document.querySelector("#report-grounding-title").textContent = modelWroteText
    ? t("Metin yerel model tarafından yazıldı")
    : groundingSources.length ? t("Yerelde işlendi, kaynaklarla desteklendi") : t("Yerelde işlendi");
  const groundingDetail = groundingSources.length ? `ONNX → SQLite → RAG → Foundry Local · ${groundingSources.length} ${t("kaynak")}` : t("Kaynak kaydı yok · SQLite olay geçmişi");
  renderReportSources(groundingSources);
  renderModelDecision(report.assessment);
  document.querySelector("#report-grounding-detail").textContent = modelWroteText ? `${t("Karar deterministik doğrulayıcıdan geldi")} · ${groundingDetail}` : groundingDetail;
  const scopeDate = value => new Intl.DateTimeFormat(currentLanguage === "tr" ? "tr-TR" : "en-GB", { dateStyle: "short" }).format(new Date(value));
  const scopeHives = report.hive_ids || [];
  document.querySelector("#report-scope").textContent = `${scopeDate(report.period_start)} – ${scopeDate(report.period_end)} · ${scopeHives.length ? scopeHives.join(", ") : t("Tüm kovanlar")}`;
  // The chain a report rests on begins at the acoustic model that measured these events,
  // and the page named only the model that phrased them. Every event carries the ONNX
  // profile that decided it, so the first link can be shown rather than assumed.
  const reportPeriodStart = new Date(report.period_start), reportPeriodEnd = new Date(report.period_end);
  const measurementModels = [...new Set(alarmEvents
    .filter(event => {
      const at = new Date(event.timestamp);
      return at >= reportPeriodStart && at <= reportPeriodEnd
        && (!scopeHives.length || scopeHives.includes(event.hive_id));
    })
    .map(event => event.model)
    .filter(Boolean))];
  const measurementLine = document.querySelector("#report-measurement");
  measurementLine.textContent = measurementModels.length
    ? `${t("Ölçüm modeli")}: ${measurementModels.join(", ")} · ONNX Runtime`
    : "";
  measurementLine.hidden = measurementModels.length === 0;
  document.querySelector("#report-summary").textContent = explainHiveIds(report.summary);
  document.querySelector("#report-file-name").textContent = `${reportTypeLabel(report.report_type || "weekly")} ${currentLanguage === "en" ? "report" : "rapor"}`;
  document.querySelector("#report-file-meta").textContent = `PDF · ${scopeDate(report.period_end)}`;
  const periodStart = new Date(report.period_start);
  const periodEnd = new Date(report.period_end);
  const inspections = alarmEvents.filter(event => event.acknowledged_at && new Date(event.timestamp) >= periodStart && new Date(event.timestamp) <= periodEnd);
  [["#report-confirmed-count","issue_confirmed"],["#report-cleared-count","no_issue_found"],["#report-uncertain-count","uncertain"]].forEach(([selector,result]) => {
    const count = inspections.filter(event => event.inspection_result === result).length;
    const element = document.querySelector(selector);
    element.textContent = count;
    element.closest(".inspection-row").classList.toggle("is-active", count > 0);
  });
  reportPdfDownload.href = `/api/reports/${report.id}/pdf?preview=true`;
  reportPdfDownload.dataset.reportId = String(report.id);
  // Reports are generated per language, and the picker only lists the current one.
  // Surface the sibling so the other language is reachable without switching the panel.
  const sibling = allReports.find(item =>
    item.id !== report.id
    && (item.language || "tr") !== (report.language || "tr")
    && item.period_start === report.period_start
    && item.period_end === report.period_end
  );
  const otherLink = document.querySelector("#report-pdf-other");
  otherLink.hidden = !sibling;
  if (sibling) {
    otherLink.href = `/api/reports/${sibling.id}/pdf?preview=true`;
    otherLink.textContent = (sibling.language || "tr") === "en" ? t("İngilizce PDF") : t("Türkçe PDF");
  }
  renderReportCharts(report);
  translatePage(document.querySelector("#reports-view"));
}

async function downloadSelectedReportPdf(event) {
  const reportId = reportPdfDownload.dataset.reportId;
  if (!reportId || reportPdfDownload.getAttribute("aria-busy") === "true") return;

  // Plain HTTP/LAN pages cannot use Chromium's protected file picker. Open the
  // PDF inline instead of triggering an insecure download; the viewer can print
  // or save it without the mixed-download block.
  if (!window.isSecureContext || !("showSaveFilePicker" in window)) return;

  event.preventDefault();

  const originalLabel = reportPdfDownload.textContent;
  reportPdfDownload.setAttribute("aria-busy", "true");
  reportPdfDownload.textContent = currentLanguage === "en" ? "Preparing PDF…" : "PDF hazırlanıyor…";

  try {
    let fileHandle = null;
    if (window.isSecureContext && "showSaveFilePicker" in window) {
      fileHandle = await window.showSaveFilePicker({
        suggestedName: `waggle-report-${reportId}.pdf`,
        types: [{ description: "PDF document", accept: { "application/pdf": [".pdf"] } }],
      });
    }

    const response = await fetch(`/api/reports/${encodeURIComponent(reportId)}/pdf`, {
      credentials: "same-origin",
      headers: { Accept: "application/pdf" },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || (currentLanguage === "en" ? "PDF could not be downloaded." : "PDF indirilemedi."));
    }

    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = filenameMatch?.[1] || `waggle-report-${reportId}.pdf`;

    if (fileHandle) {
      const writable = await fileHandle.createWritable();
      await writable.write(blob);
      await writable.close();
      reportPdfDownload.textContent = currentLanguage === "en" ? "PDF saved" : "PDF kaydedildi";
      await new Promise(resolve => window.setTimeout(resolve, 900));
      return;
    }

    const objectUrl = URL.createObjectURL(blob);
    const temporaryLink = document.createElement("a");
    temporaryLink.href = objectUrl;
    temporaryLink.download = filename;
    temporaryLink.hidden = true;
    document.body.appendChild(temporaryLink);
    temporaryLink.click();
    temporaryLink.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  } catch (error) {
    if (error?.name === "AbortError") return;
    window.alert(error.message);
  } finally {
    reportPdfDownload.removeAttribute("aria-busy");
    reportPdfDownload.textContent = originalLabel;
  }
}

async function acknowledgeEvent(eventId, result, note) {
  const response = await fetch(`/api/events/${eventId}/acknowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ result, note: note || null }),
  });
  if (!response.ok) throw new Error(t("Alarm onaylanamadı"));
  // Hold the card open long enough to read what was just recorded. Without this the row
  // it becomes appears in place of the button that was clicked, which reads as a failure.
  justResolvedAlarm = String(eventId);
  clearTimeout(justResolvedTimer);
  justResolvedTimer = setTimeout(() => {
    // Removing the card in one frame reads as the panel snatching it away before the
    // outcome could be read, so it fades first and leaves on its own. Where the filter
    // still holds it — "Tümü", or the hive's other alarms — it settles into a row instead.
    // A re-render meanwhile leaves nothing to fade, and that case just settles.
    const card = alarmsList.querySelector(".alarm-card.just-resolved");
    const settle = () => { justResolvedAlarm = ""; renderAlarms(); };
    if (!card) return settle();
    card.classList.add("settling");
    setTimeout(settle, ALARM_SETTLE_MS);
  }, JUST_RESOLVED_MS);
  await refresh();
  await refreshAlarms();
}

// Icons for the alarm rail. They carry no meaning on their own — every one sits beside
// its own label — so they stay decorative to a screen reader.
const ICON_WAVE = `<svg class="alarm-metric-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12h2.6l2.1-6.6 3.2 13.2 2.9-9.4 1.9 5 1.6-3.2H22"/></svg>`;
const ICON_SEVERITY = `<svg class="alarm-metric-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11.5" cy="12.5" r="7.2"/><circle cx="11.5" cy="12.5" r="2.8"/><path d="m17.4 6.6 3.1-3.1M18.2 3.4v3.3h3.3"/></svg>`;
const ICON_RUN = `<svg class="alarm-metric-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12.5" r="7.6"/><path d="M12 8.4v4.4l2.9 1.8"/></svg>`;
const ICON_GUIDANCE = `<svg class="alarm-guidance-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.6A1.6 1.6 0 0 1 5.6 4H11v15.4H5.6A1.6 1.6 0 0 0 4 21Z"/><path d="M20 5.6A1.6 1.6 0 0 0 18.4 4H13v15.4h5.4A1.6 1.6 0 0 1 20 21Z"/></svg>`;
const ICON_CLIPBOARD = `<svg class="alarm-button-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9.2 3.8h5.6v3.1H9.2z"/><path d="M15.6 5.4h2A1.6 1.6 0 0 1 19.2 7v12.6a1.6 1.6 0 0 1-1.6 1.6H6.4a1.6 1.6 0 0 1-1.6-1.6V7a1.6 1.6 0 0 1 1.6-1.6h2"/></svg>`;

function alarmPastCountLabel(count) {
  return currentLanguage === "en"
    ? `${count} past ${count === 1 ? "record" : "records"}`
    : `${count} geçmiş kayıt`;
}

// English counts its nouns and Turkish does not, so this is built rather than looked up:
// the dictionary maps whole strings, and "2 aktif alarm" would have to be listed per count.
function alarmOpenPillLabel(count) {
  return currentLanguage === "en"
    ? `${count} open ${count === 1 ? "alert" : "alerts"}`
    : `${count} aktif alarm`;
}

// Seconds belong in the event table, where one row is compared with the next. A card is
// scanned, so it gets the shape a person would say out loud: "3 Eyl 2026 · 22:49".
function alarmDateLabel(value) {
  const locale = currentLanguage === "tr" ? "tr-TR" : "en-GB";
  const date = new Date(value);
  const day = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" }).format(date);
  const time = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(date);
  return `${day} · ${time}`;
}

// An alarm is the first step of a three-step job, and the card used to show only the
// button for step two. Naming all three says what "completing" the inspection commits to.
function alarmStepsMarkup(event) {
  const steps = [
    { label: "Alarm algılandı", done: true },
    { label: "Fiziksel kontrol", done: Boolean(event.acknowledged_at) },
    { label: event.inspection_result ? "Sonuç kaydedildi" : "Sonucu kaydet", done: Boolean(event.inspection_result) },
  ];
  const settled = steps.every(step => step.done);
  return `<ol class="alarm-steps${settled ? " settled" : ""}">${steps.map((step, index) =>
    // A finished step is a tick, not a number: the numbers are there to say what order
    // the work goes in, and once it is done the order is no longer the useful part.
    `<li class="alarm-step ${step.done ? "done" : "todo"}" style="--step-order:${index}"><span class="alarm-step-mark">${settled ? "✓" : index + 1}</span><span class="alarm-step-label">${t(step.label)}</span></li>`).join("")}</ol>`;
}

// The two numbers answer different questions — how much of the recording moved, and how
// far it moved — so they are shown as two tiles rather than one run-on line. A number that
// was never measured says so, because a blank tile reads as zero.
function alarmMetricsMarkup(event) {
  const tiles = [
    { icon: ICON_WAVE, label: "Aykırı ses", value: Number(event.anomaly_fraction), missing: "Ölçülmedi" },
    { icon: ICON_SEVERITY, label: "Sapma şiddeti", value: Number(event.anomaly_severity), missing: "Ölçülmedi" },
  ];
  return `<div class="alarm-metrics">${tiles.map(tile => `
    <div class="alarm-metric">${tile.icon}<div><span>${t(tile.label)}</span><strong>${Number.isFinite(tile.value) ? pct(Math.round(tile.value * 100)) : t(tile.missing)}</strong></div></div>`).join("")}</div>`;
}

// The newest alarm on a hive is the one being worked, so it is the one opened: the whole
// card, with the measurements and the action beside it. Older ones collapse to a row.
function alarmFeaturedCard(event, chronological) {
  const acknowledged = Boolean(event.acknowledged_at);
  return acknowledged ? alarmResolvedCard(event) : alarmOpenCard(event, chronological);
}

function alarmOpenCard(event, chronological) {
  const repeat = alarmRepeatLabel(event, chronological);
  return `
        <article class="alarm-card featured open">
          <div class="alarm-icon" aria-hidden="true">!</div>
          <div class="alarm-content">
            <div class="alarm-card-head"><div><span class="alarm-live-state">${t("Aktif")}</span><span>${alarmDateLabel(event.timestamp)}</span>${repeat ? `<span class="alarm-repeat">${escapeHtml(repeat)}</span>` : ""}</div></div>
            <h3>${t("Kalıcı akustik değişim")}</h3>
            <p>${escapeHtml(alarmSummary(event))}</p>
            <div class="alarm-guidance" data-alarm-guidance="${event.id}" hidden></div>
          </div>
          <div class="alarm-rail">
            ${alarmStepsMarkup(event)}
            ${alarmMetricsMarkup(event)}
            <div class="alarm-rail-actions">
              <button class="alarm-primary-button" data-alarm-ack="${event.id}" type="button">${ICON_CLIPBOARD}${t("Fiziksel kontrolü başlat")}</button>
              <button class="alarm-secondary-link" data-hive-detail="${escapeHtml(event.hive_id)}" type="button">${t("Kovanı incele")} <span aria-hidden="true">→</span></button>
            </div>
          </div>
        </article>`;
}

// A closed alarm is a record, so it stops shouting: the red goes, the reading moves under
// a label saying when it was taken, and what the inspection found takes the front.
function alarmResolvedCard(event) {
  const fresh = String(event.id) === justResolvedAlarm;
  const outcome = event.inspection_result === "issue_confirmed" ? "Sorun doğrulandı"
    : event.inspection_result === "no_issue_found" ? "Belirgin sorun görülmedi" : "Belirsiz";
  const by = [event.acknowledged_by ? `${t("Kontrol eden")}: ${escapeHtml(event.acknowledged_by)}` : "", alarmDateLabel(event.acknowledged_at)]
    .filter(Boolean).join(" · ");
  return `
        <article class="alarm-card featured resolved${fresh ? " just-resolved" : ""}">
          <div class="alarm-icon" aria-hidden="true">✓</div>
          <div class="alarm-content">
            <div class="alarm-card-head"><div><span class="alarm-live-state">${t("Kapandı")}</span><span>${alarmDateLabel(event.acknowledged_at)}</span></div></div>
            <h3>${t("Fiziksel kontrol tamamlandı")}</h3>
            <p>${t("Alarm saha kontrolüyle kapatıldı. Yeni bir kalıcı değişim algılanırsa tekrar bildirim oluşturulur.")}</p>
            ${fresh ? `<p class="alarm-saved-note"><span aria-hidden="true">✓</span>${t("Kayıt başarıyla kaydedildi")}</p>` : ""}
            <div class="alarm-outcome">
              <p class="alarm-outcome-label">${t("Kontrol sonucu")}</p>
              <span class="alarm-outcome-chip">${t(outcome)}</span>
              ${event.inspection_note ? `<p class="alarm-outcome-note">${escapeHtml(event.inspection_note)}</p>` : ""}
              ${by ? `<p class="alarm-outcome-by">${by}</p>` : ""}
            </div>
          </div>
          <div class="alarm-rail">
            ${alarmStepsMarkup(event)}
            <p class="alarm-metrics-label">${t("Alarm anındaki ölçüm")}</p>
            ${alarmMetricsMarkup(event)}
            <div class="alarm-rail-actions">
              <button class="alarm-secondary-link" data-hive-detail="${escapeHtml(event.hive_id)}" type="button">${t("Kovanı incele")} <span aria-hidden="true">→</span></button>
            </div>
          </div>
        </article>`;
}

// One line for an alarm that is no longer the live one, carrying the same facts in the
// order they are scanned. It opens into the full card on request.
function alarmCompactRow(event) {
  const acknowledged = Boolean(event.acknowledged_at);
  const fraction = Number(event.anomaly_fraction);
  const severity = Number(event.anomaly_severity);
  return `
        <article class="alarm-card compact ${acknowledged ? "resolved" : "open"}">
          <span class="alarm-row-dot" aria-hidden="true">${acknowledged ? "✓" : "!"}</span>
          <span class="alarm-row-date">${alarmDateLabel(event.timestamp)}</span>
          <span class="alarm-live-state">${t(acknowledged ? "Kapandı" : "Aktif")}</span>
          <strong class="alarm-row-title">${t("Kalıcı akustik değişim")}</strong>
          <span class="alarm-row-metric">${ICON_WAVE}${Number.isFinite(fraction) ? `${pct(Math.round(fraction * 100))} ${t("aykırı ses")}` : t("Aykırı ses ölçülmedi")}</span>
          <span class="alarm-row-metric">${ICON_SEVERITY}${Number.isFinite(severity) ? `${pct(Math.round(severity * 100))} ${t("sapma şiddeti")}` : t("Şiddet ölçülmedi")}</span>
          <button class="alarm-row-expand" data-alarm-expand="${event.id}" type="button">${t("Detayları aç")} <span aria-hidden="true">⌄</span></button>
        </article>`;
}

// Every alarm card carried the same two sentences, so two alerts on one hive were told
// apart only by their timestamps: a beekeeper could not see whether the second one was a
// new problem or the first one continuing. What the monitor measured says more. The
// unbroken run is why the alarm fired at all — the threshold is 30 windows of one second
// — and it is the number that can be acted on.
function alarmSummary(event) {
  const english = currentLanguage === "en";
  const sentences = [];

  const run = Number(event.consecutive_anomalies);
  if (Number.isFinite(run) && run > 0) {
    sentences.push(english
      ? `The sound stayed outside this hive's normal range for ${run} unbroken seconds.`
      : `Ses, bu kovanın normal aralığının dışında ${run} saniye kesintisiz kaldı.`);
  }

  const fraction = Number(event.anomaly_fraction);
  if (Number.isFinite(fraction)) {
    const share = Math.round(fraction * 100);
    // Turkish suffixes agree with the vowel of the number they follow, which a template
    // cannot know, so the ratio is stated as its own clause rather than inflected.
    sentences.push(share >= 100
      ? (english ? "Every second of the recording deviated." : "Kaydın tamamı normal aralığın dışındaydı.")
      : (english ? `${share}% of the recording fell outside it.` : `Normal aralığın dışında kalan kayıt oranı: ${pct(share)}.`));
  }

  sentences.push(t("Kovanın fiziksel olarak kontrol edilmesi öneriliyor."));
  return sentences.join(" ");
}

// "Is this new, or the one from this morning still going?" is the first question an alarm
// raises and the card could not answer it. Counting from the oldest is how a person counts.
function alarmRepeatLabel(event, chronological) {
  const order = chronological.findIndex(item => item.id === event.id) + 1;
  if (order < 2) return "";
  const previous = chronological[order - 2];
  return currentLanguage === "en"
    ? `Alarm ${order} on this hive · previous ${alarmDateLabel(previous.timestamp)}`
    : `Bu kovandaki ${order}. alarm · önceki ${alarmDateLabel(previous.timestamp)}`;
}

function renderAlarms() {
  const criticalEvents = alarmEvents.filter(event => event.status === "ALARM");
  const openEvents = criticalEvents.filter(event => !event.acknowledged_at);
  const navCount = document.querySelector("#nav-alarm-count");
  navCount.textContent = openEvents.length;
  navCount.hidden = openEvents.length === 0;
  document.querySelector("#open-alarm-count").textContent = openEvents.length;
  const alarmSoundState = document.querySelector("#alarm-sound-state");
  if (alarmSoundState) alarmSoundState.textContent = t(`Sesli uyarı ${soundEnabled ? "açık" : "kapalı"}`);
  const filterValue = alarmFilter.dataset.value || "open";
  const hiveQuery = alarmHiveSearch.value.trim().toLocaleLowerCase(currentLanguage === "tr" ? "tr-TR" : "en-US");
  const filtered = criticalEvents.filter(event => {
    // The list defaults to the open alarms, and completing an inspection is exactly what
    // stops an alarm being open — so the card vanished the instant the button was pressed,
    // before it could show what had been recorded. The one just closed stays until it has
    // finished settling, whatever the filter says.
    const matchesStatus = String(event.id) === justResolvedAlarm || filterValue === "all" ||
      (filterValue === "open" && !event.acknowledged_at) ||
      (filterValue === "acknowledged" && event.acknowledged_at);
    const hiveText = `${hiveLabel(event.hive_id)} ${event.hive_id}`.toLocaleLowerCase(currentLanguage === "tr" ? "tr-TR" : "en-US");
    return matchesStatus && (!hiveQuery || hiveText.includes(hiveQuery));
  });
  const grouped = filtered.reduce((groups, event) => {
    if (!groups[event.hive_id]) groups[event.hive_id] = [];
    groups[event.hive_id].push(event);
    return groups;
  }, {});
  alarmsList.innerHTML = filtered.length ? Object.entries(grouped).map(([hiveId, events], groupIndex) => {
    // Oldest first, so an alarm can say which one it is in this hive's sequence.
    const chronological = [...events].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    // Newest first for display: the live alarm is the one being worked, so it leads.
    const newestFirst = [...chronological].reverse();
    const openInGroup = events.filter(item => !item.acknowledged_at).length;
    // The card that opens is the alarm still being worked. A hive whose alarms are all
    // closed keeps them as rows: they are a record, and a record does not need the room.
    const featuredId = newestFirst.some(item => String(item.id) === justResolvedAlarm)
      ? justResolvedAlarm
      : String(newestFirst.find(item => !item.acknowledged_at)?.id ?? "");
    return `
    <section class="alarm-hive-group ${collapsedAlarmHives.has(hiveId) ? "collapsed" : ""}" data-alarm-hive="${escapeHtml(hiveId)}">
      <header class="alarm-hive-head">
        <span class="managed-hive-icon hive-tone-${groupIndex % 3}" aria-hidden="true"><svg viewBox="0 0 54 54"><path class="hive-roof" d="M15 17.5 21 11h12l6 6.5"></path><path class="hive-body" d="M14.5 18h25l3 6.5-2.7 6 1.5 6.5-4.8 6H17.5l-4.8-6 1.5-6.5-2.7-6 3-6.5Z"></path><path class="hive-band" d="M13 24.5h28M14.2 30.5h25.6M13.3 37h27.4"></path><path class="hive-feet" d="M18 43v3M36 43v3"></path><ellipse class="hive-door" cx="27" cy="38.5" rx="4.2" ry="4.8"></ellipse></svg></span>
        <div class="alarm-hive-title"><h3>${escapeHtml(hiveLabel(hiveId))}</h3>${openInGroup
          ? `<span class="alarm-open-pill">${alarmOpenPillLabel(openInGroup)}</span>`
          : `<span class="alarm-open-pill closed">${t("Alarm kapandı")}</span><span class="alarm-past-count">${alarmPastCountLabel(events.length)}</span>`}</div>
        <button class="alarm-hive-toggle" data-alarm-hive-toggle type="button" aria-expanded="${String(!collapsedAlarmHives.has(hiveId))}" aria-label="${t("Kovanın alarmlarını aç veya kapat")}"><span aria-hidden="true">⌃</span></button>
      </header>
      <div class="alarm-hive-events">${newestFirst.map(event =>
        String(event.id) === featuredId || expandedAlarms.has(String(event.id))
          ? alarmFeaturedCard(event, chronological)
          : alarmCompactRow(event)).join("")}</div>
    </section>`;
  }).join("") : `<div class="empty-state"><strong>${t(filterValue === "open" ? "Açık alarm yok" : "Bu filtrede alarm yok")}</strong><p>${t("Kovanlarınızın kritik olayları burada görünecek.")}</p></div>`;
  hydrateAlarmGuidance();
}

// Retrieval was reachable only through report generation, so an alarm sitting on the
// screen carried no guidance until a weekly report was written about it. The same
// retriever, given the one event, answers immediately and with no model in the loop —
// which is also why it can be shown on a panel whose local model is switched off.
const alarmGuidanceCache = new Map();

async function hydrateAlarmGuidance() {
  // Only the cards a person can actually see are worth a request; the rest fill in when
  // the filter narrows to them.
  const slots = [...alarmsList.querySelectorAll("[data-alarm-guidance]")].slice(0, 12);
  for (const slot of slots) {
    const eventId = slot.dataset.alarmGuidance;
    const key = `${eventId}:${currentLanguage}`;
    let notes = alarmGuidanceCache.get(key);
    if (!notes) {
      try {
        const response = await fetch(`/api/events/${encodeURIComponent(eventId)}/guidance?language=${currentLanguage}&limit=2`);
        if (!response.ok) continue;
        notes = await response.json();
        alarmGuidanceCache.set(key, notes);
      } catch (error) {
        continue;
      }
    }
    // A re-render while a request was in flight detaches the slot it was meant for.
    if (!notes.length || !slot.isConnected) continue;
    slot.innerHTML = `<div class="alarm-guidance-head">${ICON_GUIDANCE}<p class="alarm-guidance-label">${t("Yerel kılavuz")}</p></div><ul>${notes.map(note =>
      // The note's id is a knowledge-base key: it belongs in the report and the export,
      // where provenance is checked, and not on the card a beekeeper reads in the field.
      `<li><span>${escapeHtml(note.text)}</span></li>`).join("")}</ul>`;
    slot.hidden = false;
  }
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
    if (latestReports.length) renderSelectedReport();
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
  const [weatherResponse, reportsResponse, reportEventsResponse] = await Promise.all([
    weatherRequest, fetch("/api/reports?limit=100"), fetch("/api/events?limit=500")
  ]);
  if (weatherResponse?.ok) renderWeather(await weatherResponse.json());
  else if (!currentSettings?.weather_enabled) renderWeatherDisabled();
  // Weather on and the service out of reach fell through both branches, so the card sat on
  // its initial "Yükleniyor…" for as long as the page stayed open — on a panel whose whole
  // point is that it keeps working without the internet, that is the ordinary case.
  else renderWeatherUnavailable();
  if (reportsResponse.ok) renderReports(await reportsResponse.json());
  if (reportEventsResponse.ok) { reportEvents = await reportEventsResponse.json(); if (latestReports.length) renderSelectedReport(); }
}

soundButton.addEventListener("click", async () => {
  soundEnabled = !soundEnabled;
  soundButton.textContent = t(`Sesli alarm: ${soundEnabled ? "açık" : "kapalı"}`);
  // The same switch exists on the Settings page and that one is stored, so the two used to
  // disagree the moment this was pressed: the header said off, Settings still said on, and
  // a reload restored the setting without explanation. Keep them one control.
  const checkbox = document.querySelector("#settings-sound");
  if (checkbox) checkbox.checked = soundEnabled;
  if (currentRole !== "owner" || !currentSettings) return;
  const response = await fetch("/api/settings", {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({...currentSettings, sound_enabled: soundEnabled}),
  }).catch(() => null);
  if (response && response.ok) currentSettings = await response.json();
});
sensorButton.addEventListener("click", analyzeSensorAudio);
sensorAudio.addEventListener("change", renderSensorQueue);
document.querySelector("#live-record-toggle").addEventListener("click", toggleLiveRecording);
document.querySelector(".sensor-source-tabs").addEventListener("click", event => {
  const button = event.target.closest("[data-sensor-source]");
  if (button) selectSensorSource(button.dataset.sensorSource);
});
document.querySelector("#sensor-queue").addEventListener("click", event => {
  const drop = event.target.closest("[data-drop-clip]");
  if (!drop) return;
  liveClips.splice(Number(drop.dataset.dropClip), 1);
  renderSensorQueue();
});
eventFilter.addEventListener("change", renderEvents);
alarmFilter.addEventListener("click", event => {
  const button = event.target.closest("[data-alarm-filter]");
  if (!button) return;
  alarmFilter.dataset.value = button.dataset.alarmFilter;
  alarmFilter.querySelectorAll("[data-alarm-filter]").forEach(item => item.classList.toggle("active", item === button));
  renderAlarms();
});
alarmHiveSearch.addEventListener("input", renderAlarms);
reportSelect.addEventListener("change", renderSelectedReport);
reportPdfDownload.addEventListener("click", downloadSelectedReportPdf);
document.querySelector(".report-type-tabs").addEventListener("click", event => {
  const button = event.target.closest("[data-report-type]");
  if (!button) return;
  activeReportType = button.dataset.reportType;
  document.querySelectorAll("[data-report-type]").forEach(item => item.classList.toggle("active", item === button));
  renderReports(allReports);
});
["#report-hive-filter", "#report-date-start", "#report-date-end"].forEach(selector => document.querySelector(selector).addEventListener("change", () => renderReports(allReports)));
document.querySelector("#report-apply-filters").addEventListener("click", () => {
  renderReports(allReports);
  const count = document.querySelector("#report-filter-count").textContent;
  showReportNotice(count || `${latestReports.length} ${t("rapor eşleşti")}`);
});
document.querySelector("#report-clear-filters").addEventListener("click", () => {
  activeReportType = "all";
  document.querySelectorAll("[data-report-type]").forEach(item => item.classList.toggle("active", item.dataset.reportType === "all"));
  document.querySelector("#report-hive-filter").value = "all";
  document.querySelector("#report-date-start").value = "";
  document.querySelector("#report-date-end").value = "";
  renderReports(allReports);
});

// The native dropdown is drawn by the operating system and cannot be styled, so the
// select is kept as the source of truth and a listbox is layered over it.
function enhanceSelect(select) {
  if (select.dataset.enhanced) return;
  select.dataset.enhanced = "1";

  const shell = document.createElement("div");
  shell.className = "select-shell";
  select.parentNode.insertBefore(shell, select);
  shell.appendChild(select);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "select-button";
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");

  const menu = document.createElement("div");
  menu.className = "select-menu";
  menu.setAttribute("role", "listbox");
  menu.hidden = true;

  shell.append(button, menu);

  const close = () => { menu.hidden = true; button.setAttribute("aria-expanded", "false"); };

  const sync = () => {
    const selected = select.options[select.selectedIndex];
    button.innerHTML = `<span>${escapeHtml(selected ? selected.textContent : "")}</span><i aria-hidden="true"></i>`;
    button.disabled = select.disabled;
    menu.innerHTML = [...select.options].map((option, index) =>
      `<button type="button" role="option" aria-selected="${index === select.selectedIndex}" data-index="${index}"${index === select.selectedIndex ? ' class="is-selected"' : ""}>${escapeHtml(option.textContent)}</button>`
    ).join("");
  };

  button.addEventListener("click", event => {
    event.stopPropagation();
    document.querySelectorAll(".select-menu").forEach(other => { if (other !== menu) other.hidden = true; });
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    button.setAttribute("aria-expanded", String(willOpen));
  });

  menu.addEventListener("click", event => {
    const option = event.target.closest("[data-index]");
    if (!option) return;
    select.selectedIndex = Number(option.dataset.index);
    select.dispatchEvent(new Event("change", {bubbles: true}));
    sync();
    close();
  });

  button.addEventListener("keydown", event => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const next = select.selectedIndex + (event.key === "ArrowDown" ? 1 : -1);
    if (next < 0 || next >= select.options.length) return;
    select.selectedIndex = next;
    select.dispatchEvent(new Event("change", {bubbles: true}));
    sync();
  });

  document.addEventListener("click", event => { if (!shell.contains(event.target)) close(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") close(); });

  // Option lists are rebuilt by the panel (hive filters, device lists), and translatePage
  // rewrites their labels, so the overlay follows the select rather than snapshotting it.
  new MutationObserver(sync).observe(select, {childList: true, subtree: true, characterData: true});
  select.addEventListener("change", sync);

  sync();
}

// #settings-refresh is deliberately absent: its five choices are drawn as a segmented row
// by syncRefreshSegments, and it was still being enhanced into a dropdown as well — so the
// Settings page carried two working controls for the refresh interval, stacked, and moving
// one did not visibly move the other.
["#event-filter", "#report-hive-filter", "#health-evidence", "#device-kind", "#sensor-device", "#settings-language", "#export-format", "#export-period"]
  .forEach(selector => { const select = document.querySelector(selector); if (select) enhanceSelect(select); });

document.querySelector("#report-history-open").addEventListener("click", () => reportPickerButton.click());

// Searching the history is a tool, not the report. It used to sit open between the page
// title and the verdict, so the answer a beekeeper came for started a screen and a half
// down; "Dönemi değiştir" then scrolled to a panel that was already on screen. Closed by
// default, it gives that space back and the button now actually opens something.
function setReportFilters(open) {
  const controls = document.querySelector(".report-controls");
  const toggle = document.querySelector("#report-controls-toggle");
  controls.classList.toggle("is-collapsed", !open);
  toggle.setAttribute("aria-expanded", String(open));
}

document.querySelector("#report-controls-toggle").addEventListener("click", () => {
  setReportFilters(document.querySelector(".report-controls").classList.contains("is-collapsed"));
});

document.querySelector("#report-period-jump").addEventListener("click", () => {
  const controls = document.querySelector(".report-controls");
  setReportFilters(true);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  controls.scrollIntoView({behavior: reduceMotion ? "auto" : "smooth", block: "center"});
  controls.classList.add("is-highlighted");
  setTimeout(() => controls.classList.remove("is-highlighted"), 1600);
  document.querySelector("#report-date-start").focus({preventScroll: true});
});

const reportGenerateButton = document.querySelector("#report-generate");
const reportProgress = document.querySelector("#report-generate-progress");
let reportGenerationPoll = null;

function watchReportGeneration() {
  clearInterval(reportGenerationPoll);
  reportGenerationPoll = setInterval(async () => {
    const status = await refreshReportGeneration();
    if (!status || status.running) return;
    clearInterval(reportGenerationPoll);
    if (status.error) showReportNotice(`${t("Rapor üretilemedi")}: ${status.error}`);
    else if (!status.created) showReportNotice(t("Bu dönemde rapor üretilecek olay bulunmadı"));
    else {
      showReportNotice(`${status.created} ${t("rapor üretildi")}`);
      refresh();
    }
  }, 2000);
}

function showReportNotice(message) {
  alertEl.textContent = message;
  alertEl.classList.add("show");
  setTimeout(() => alertEl.classList.remove("show"), 5500);
}

// The two facts worth knowing while the model writes: which unit it runs on, and how far
// it has got. As chips rather than clauses appended to a sentence — the sentence grew a
// tail that read as broken output, and the numbers were unfindable inside it.
function reportProgressChips(status) {
  const chips = [];
  if (status.device) chips.push(escapeHtml(String(status.device)));
  if (status.written_characters) chips.push(`${Number(status.written_characters).toLocaleString(currentLanguage === "en" ? "en-GB" : "tr-TR")} ${t("karakter")}`);
  return chips;
}

function renderReportProgress(status) {
  const stalled = Boolean(status.stalled);
  const elapsed = Math.max(0, status.elapsed_seconds || 0);
  reportProgress.hidden = false;
  reportProgress.classList.toggle("is-stalled", stalled);
  document.querySelector("#report-progress-state").textContent = stalled ? t("Yanıt gelmiyor") : t("Rapor üretiliyor");
  document.querySelector("#report-progress-clock").textContent = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}`;
  // Silence is the stalled case; a rising character count is the merely slow one, and
  // before the answer arrived token by token the two looked identical from here.
  const note = document.querySelector("#report-generate-note");
  note.classList.toggle("is-stalled", stalled);
  note.textContent = stalled
    ? t("Model uzun süredir yanıt vermiyor. Sunucu günlüğüne bakın; panel çalışmaya devam ediyor.")
    : t("Model cihazda çalışıyor. Bu donanımda genellikle 3–5 dakika sürer; bu sırada paneli kullanmaya devam edebilirsiniz.");
  document.querySelector("#report-progress-meta").innerHTML = reportProgressChips(status).map(chip => `<li>${chip}</li>`).join("");
}

async function refreshReportGeneration() {
  try {
    const status = await (await fetch("/api/reports/generation-status")).json();
    if (!status.enabled) {
      reportGenerateButton.hidden = true;
      reportProgress.hidden = true;
      return status;
    }
    // The button and the progress card are the same slot in two states, never both: a
    // disabled button carrying its own counter read as a control that had broken.
    reportGenerateButton.hidden = Boolean(status.running);
    reportGenerateButton.disabled = Boolean(status.running);
    if (!status.running) {
      reportGenerateButton.textContent = t("Yeni rapor üret");
      reportProgress.hidden = true;
      return status;
    }
    renderReportProgress(status);
    return status;
  } catch (error) {
    reportGenerateButton.hidden = true;
    reportProgress.hidden = true;
    return null;
  }
}

reportGenerateButton.addEventListener("click", async () => {
  reportGenerateButton.disabled = true;
  // Swap to the progress card on the click rather than on the first poll, so the press
  // has an answer immediately instead of a second of an unchanged button.
  reportGenerateButton.hidden = true;
  renderReportProgress({elapsed_seconds: 0});
  try {
    const response = await fetch("/api/reports/generate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({report_type: activeReportType === "daily" ? "daily" : "weekly"}),
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
    watchReportGeneration();
  } catch (error) {
    reportGenerateButton.disabled = false;
    reportGenerateButton.hidden = false;
    reportGenerateButton.textContent = t("Yeni rapor üret");
    reportProgress.hidden = true;
    showReportNotice(`${t("Rapor üretilemedi")}: ${error.message}`);
  }
});

reportPickerButton.addEventListener("click", () => {
  const willOpen = reportPickerMenu.hidden;
  reportPickerMenu.hidden = !willOpen;
  reportPickerButton.setAttribute("aria-expanded", String(willOpen));
});
reportPickerMenu.addEventListener("click", event => {
  const button = event.target.closest("[data-report-id]");
  if (!button) return;
  reportSelect.value = button.dataset.reportId;
  reportPickerMenu.hidden = true;
  reportPickerButton.setAttribute("aria-expanded", "false");
  renderSelectedReport();
});
document.addEventListener("click", event => {
  // The history shortcut lives outside the picker, so it must be exempt from the
  // click-outside rule that would otherwise close the menu it just opened.
  if (event.target.closest(".report-picker, #report-history-open")) return;
  reportPickerMenu.hidden = true;
  reportPickerButton.setAttribute("aria-expanded", "false");
});
eventsEl.addEventListener("click", event => {
  const button = event.target.closest("[data-ack]");
  if (button) acknowledgeEvent(button.dataset.ack);
  const guidance = event.target.closest("[data-event-guidance]");
  if (!guidance) return;
  const eventId = guidance.dataset.eventGuidance;
  const row = eventsEl.querySelector(`[data-guidance-for="${eventId}"]`);
  const opening = row.hidden;
  row.hidden = !opening;
  guidance.setAttribute("aria-expanded", String(opening));
  if (opening) {
    expandedEventGuidance.add(eventId);
    fillEventGuidance(eventId);
  } else {
    expandedEventGuidance.delete(eventId);
  }
});
hivesEl.addEventListener("click", event => {
  const button = event.target.closest("[data-hive-detail]");
  if (button) openHiveDetail(button.dataset.hiveDetail);
});
["#report-actions", "#report-verdict"].forEach(selector => {
  document.querySelector(selector).addEventListener("click", event => {
    const button = event.target.closest("[data-hive-detail]");
    if (button) openHiveDetail(button.dataset.hiveDetail);
  });
});
// The two segmented controls above the chart. Both only change what is drawn, so the
// selection lives on the group element and the render reads it back.
["#chart-range", "#chart-metric"].forEach(selector => {
  const group = document.querySelector(selector);
  group.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || button.classList.contains("active")) return;
    group.dataset.value = button.dataset.range || button.dataset.metric;
    group.querySelectorAll("button").forEach(item => item.classList.toggle("active", item === button));
    renderHiveDetail();
  });
});

document.querySelector("#detail-view").addEventListener("click", event => {
  if (event.target.closest("[data-open-alarms]")) {
    showView("alarms", true);
    return;
  }
  if (event.target.closest("[data-open-guidance]")) {
    // The reviewed notes live inside settings, so the link goes there and then to them:
    // landing at the top of a long settings page is not "opening the guidance".
    showView("settings", true);
    document.querySelector(".guidance-section")?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "start",
    });
    return;
  }
  const ack = event.target.closest("[data-alarm-ack]");
  if (!ack) return;
  pendingAlarmId = ack.dataset.alarmAck;
  const dialog = document.querySelector("#alarm-confirm-dialog");
  translatePage(dialog);
  dialog.showModal();
});

document.querySelector("#back-overview").addEventListener("click", () => {
  selectedHiveId = null;
  showView("overview", true);
});
document.querySelectorAll(".nav-button").forEach(button => button.addEventListener("click", () => {
  selectedHiveId = null;
  showView(button.dataset.view, true);
}));
// The brand is an anchor so it behaves like a link for the keyboard, but the view change
// is handled here: the hash router deliberately ignores "overview", so following the href
// on its own would do nothing.
document.querySelector(".panel-brand").addEventListener("click", event => {
  event.preventDefault();
  selectedHiveId = null;
  showView("overview", true);
});
window.addEventListener("resize", () => updateNavIndicator());
requestAnimationFrame(() => updateNavIndicator());
// The underline was only repositioned on click and on window resize, so anything else
// that changed a button's width left it sitting off the label: switching language
// (Raporlar → Reports is 9px narrower), the alarm badge appearing after the first fetch,
// or a webfont arriving late. Watching the buttons themselves catches all of them.
if (window.ResizeObserver) {
  const navResize = new ResizeObserver(() => updateNavIndicator());
  document.querySelectorAll(".nav-button").forEach(button => navResize.observe(button));
}
document.fonts?.ready.then(() => updateNavIndicator());
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
  const deleteButton = event.target.closest("[data-delete-hive]");
  if (archiveButton) setHiveActive(archiveButton.dataset.archiveHive, false);
  if (restoreButton) setHiveActive(restoreButton.dataset.restoreHive, true);
  if (deleteButton) openHiveDeleteDialog(deleteButton.dataset.deleteHive);
});

const hiveDeleteDialog = document.querySelector("#hive-delete-dialog");
let pendingHiveDelete = null;

async function openHiveDeleteDialog(hiveId) {
  try {
    const footprint = await (await fetch(`/api/hives/${encodeURIComponent(hiveId)}/footprint`)).json();
    pendingHiveDelete = hiveId;
    document.querySelector("#hive-delete-name").textContent = displayHiveName(footprint.name);
    document.querySelector("#hive-delete-events").textContent = footprint.events;
    document.querySelector("#hive-delete-devices").textContent = footprint.devices;
    document.querySelector("#hive-delete-message").textContent = "";
    translatePage(hiveDeleteDialog);
    hiveDeleteDialog.showModal();
  } catch (error) {
    showReportNotice(t("Kovan bilgisi alınamadı"));
  }
}

document.querySelector("#cancel-hive-delete").addEventListener("click", () => hiveDeleteDialog.close());
document.querySelector("#confirm-hive-delete").addEventListener("click", async () => {
  if (!pendingHiveDelete) return;
  const message = document.querySelector("#hive-delete-message");
  try {
    const response = await fetch(`/api/hives/${encodeURIComponent(pendingHiveDelete)}`, {method: "DELETE"});
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
    const result = await response.json();
    hiveDeleteDialog.close();
    pendingHiveDelete = null;
    showReportNotice(`${t("Kovan silindi")} · ${result.events} ${t("olay")}`);
    // The dashboard refresh alone leaves the deleted row on screen; the management
    // list has its own fetch.
    await Promise.all([refresh(), refreshManagedHives()]);
  } catch (error) {
    message.textContent = error.message;
  }
});
document.querySelector("#device-form").addEventListener("submit", addDevice);
document.querySelector("#health-confirmation-form").addEventListener("submit", saveHealthConfirmation);
document.querySelector("#close-device-panel").addEventListener("click", closeDevicePanel);
alarmsList.addEventListener("click", event => {
  const toggle = event.target.closest("[data-alarm-hive-toggle]");
  if (toggle) {
    const group = toggle.closest(".alarm-hive-group");
    const collapsed = group.classList.toggle("collapsed");
    const hiveId = group.dataset.alarmHive;
    if (collapsed) collapsedAlarmHives.add(hiveId);
    else collapsedAlarmHives.delete(hiveId);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    return;
  }
  const expand = event.target.closest("[data-alarm-expand]");
  if (expand) {
    expandedAlarms.add(expand.dataset.alarmExpand);
    renderAlarms();
    return;
  }
  const hive = event.target.closest("[data-hive-detail]");
  if (hive) {
    openHiveDetail(hive.dataset.hiveDetail);
    return;
  }
  const button = event.target.closest("[data-alarm-ack]");
  if (!button) return;
  pendingAlarmId = button.dataset.alarmAck;
  const dialog = document.querySelector("#alarm-confirm-dialog");
  translatePage(dialog);
  dialog.showModal();
});
document.querySelector("#cancel-alarm-confirm").addEventListener("click", () => {
  pendingAlarmId = null;
  document.querySelector("#alarm-confirm-dialog").close();
});
document.querySelector("#complete-alarm-confirm").addEventListener("click", async () => {
  if (!pendingAlarmId) return;
  const selected = document.querySelector('input[name="alarm-inspection-result"]:checked');
  const message = document.querySelector("#alarm-inspection-message");
  if (!selected) {
    message.textContent = t("Bir kontrol sonucu seçin.");
    return;
  }
  const eventId = pendingAlarmId;
  const note = document.querySelector("#alarm-inspection-note").value.trim();
  pendingAlarmId = null;
  document.querySelector("#alarm-confirm-dialog").close();
  await acknowledgeEvent(eventId, selected.value, note);
});
document.querySelector("#alarm-confirm-dialog").addEventListener("close", () => {
  pendingAlarmId = null;
  document.querySelectorAll('input[name="alarm-inspection-result"]').forEach(input => { input.checked = false; });
  document.querySelector("#alarm-inspection-note").value = "";
  document.querySelector("#alarm-inspection-message").textContent = "";
});
document.querySelector("#refresh-status").addEventListener("click", refreshSystemStatus);

// --- Dışa aktar ------------------------------------------------------------------
// The label, the sentence and the mark for every dataset the API can produce. Held here
// rather than in the markup because the list is now rendered from what the server says it
// holds: a dataset with no rows is still offered, but it says so before it is chosen.
const EXPORT_DATASETS = [
  {key: "hives", title: "Kovanlar", description: "Aktif ve arşivlenmiş bütün kovanların adları, konumları ve teknik kimlikleri.",
   icon: '<path d="M4 9.5 12 5l8 4.5v9L12 23l-8-4.5Z"></path><path d="M4 9.5 12 14l8-4.5M12 14v9"></path>'},
  {key: "events", title: "Tüm olaylar", description: "Model durumları, akustik değişim oranları, ölçüm koşulları ve zamanlar.",
   icon: '<path d="M3.5 17.5 9 11l4 3.5 7.5-8"></path><path d="M15.5 6.5h5v5"></path>'},
  {key: "alarms", title: "Kritik alarmlar", description: "Açık ve kontrol edilmiş ana arı kaybı şüphesi kayıtları.", tone: "alarm",
   icon: '<path d="M12 3.5 22 20H2Z"></path><path d="M12 10v4.5M12 17.2v.1"></path>'},
  {key: "reports", title: "Raporlar", description: "Haftalık değerlendirmeler, model kararları ve dayandıkları kaynaklar.",
   icon: '<path d="M6 3.5h8l4 4v13H6Z"></path><path d="M14 3.5v4h4M9 12h6M9 15.5h6M9 19h3"></path>'},
  {key: "confirmations", title: "Saha doğrulamaları", description: "Kovanı yerinde kontrol eden hesap, gözlem ve sonucun profile alınıp alınmadığı.",
   icon: '<path d="M12 3.2 19.5 6v6.4c0 4.2-3 7.6-7.5 9.4-4.5-1.8-7.5-5.2-7.5-9.4V6Z"></path><path d="m8.8 12.2 2.4 2.4 4.2-4.6"></path>'},
  {key: "enrollment", title: "Öğrenme kayıtları", description: "Kovanın profilini oluşturan kayıt defteri: hangi cihaz, hangi gün, kaç pencere. Ses dosyaları değil.",
   icon: '<path d="M12 3.5a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0v-5a3 3 0 0 1 3-3Z"></path><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M9 21h6"></path>'},
  {key: "devices", title: "Cihazlar", description: "Hangi mikrofonun hangi kovana bağlı olduğu, türü ve en son ne zaman kayıt gönderdiği.",
   icon: '<rect x="7" y="3" width="10" height="18" rx="2.4"></rect><path d="M10.6 6.2h2.8"></path><circle cx="12" cy="17.4" r="1.1"></circle>'},
  {key: "guidance", title: "Yerel kılavuz tabanı", description: "Değerlendirmelerin dayandığı gözden geçirilmiş notlar, etiketleri ve seçim koşullarıyla.",
   icon: '<path d="M5 4.5h9l5 5v10.5a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5V6A1.5 1.5 0 0 1 5 4.5Z"></path><path d="M14 4.5v5h5M8 13h8M8 16.5h5"></path>'},
];

const exportSelection = new Set();
let exportSummary = {};
let exportGroup = "all";

function exportPeriodBounds() {
  const days = Number(document.querySelector("#export-period")?.value);
  if (!days) return null;
  const since = new Date(Date.now() - days * 86400000);
  return {since: since.toISOString()};
}

async function refreshExports() {
  const bounds = exportPeriodBounds();
  const query = bounds ? `?since=${encodeURIComponent(bounds.since)}` : "";
  try {
    const response = await fetch(`/api/export/summary${query}`);
    const payload = await response.json();
    exportSummary = Object.fromEntries((payload.datasets || []).map(item => [item.dataset, item]));
  } catch (error) {
    exportSummary = {};
  }
  renderExportList();
}

function renderExportList() {
  const list = document.querySelector("#export-list");
  if (!list) return;
  const term = (document.querySelector("#export-search")?.value || "").trim().toLocaleLowerCase("tr");
  const visible = EXPORT_DATASETS.filter(dataset => {
    const summary = exportSummary[dataset.key];
    if (exportGroup !== "all" && summary && summary.group !== exportGroup) return false;
    if (!term) return true;
    return `${t(dataset.title)} ${t(dataset.description)}`.toLocaleLowerCase("tr").includes(term);
  });
  list.innerHTML = visible.map(dataset => {
    const summary = exportSummary[dataset.key] || {};
    const selected = exportSelection.has(dataset.key);
    const count = summary.count === undefined || summary.count === null
      ? "—"
      : `${Number(summary.count).toLocaleString(currentLanguage === "en" ? "en-GB" : "tr-TR")} ${t("kayıt")}`;
    return `<li><button type="button" class="export-row" data-export="${dataset.key}" aria-pressed="${selected}">
      <span class="export-check"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"></path></svg></span>
      <span class="export-row-icon${dataset.tone === "alarm" ? " is-alarm" : summary.group === "system" ? " is-system" : ""}" aria-hidden="true"><svg viewBox="0 0 24 24">${dataset.icon}</svg></span>
      <span class="export-row-copy"><strong>${t(dataset.title)}</strong><span>${t(dataset.description)}</span></span>
      <span class="export-row-count${summary.count ? "" : " is-empty"}">${count}</span>
    </button></li>`;
  }).join("");
  document.querySelector("#export-empty").hidden = visible.length > 0;
  list.querySelectorAll("[data-export]").forEach(row => {
    row.addEventListener("click", () => {
      const key = row.dataset.export;
      if (exportSelection.has(key)) exportSelection.delete(key); else exportSelection.add(key);
      row.setAttribute("aria-pressed", String(exportSelection.has(key)));
      updateExportBar();
    });
  });
  updateExportBar();
}

function updateExportBar() {
  const count = exportSelection.size;
  const label = document.querySelector("#export-selection");
  const button = document.querySelector("#export-download");
  const note = document.querySelector("#export-period-note");
  if (!label || !button) return;
  label.textContent = count ? `${count} ${t("veri türü seçildi")}` : t("Veri türü seçin");
  label.classList.toggle("is-ready", count > 0);
  button.disabled = count === 0;
  // One dataset is one file; more than one can only be an archive, and the button says
  // which is about to land rather than leaving it to be discovered in the downloads folder.
  document.querySelector("#export-download-label").textContent = count > 1 ? t("Zip olarak indir") : t("Dışa aktar");
  // A period cannot narrow the datasets that describe the setup rather than a measurement.
  const unfiltered = [...exportSelection].filter(key => exportSummary[key] && !exportSummary[key].period_filtered);
  const ranged = Boolean(exportPeriodBounds());
  note.hidden = !(ranged && unfiltered.length);
  if (!note.hidden) {
    const names = unfiltered.map(key => t(EXPORT_DATASETS.find(item => item.key === key).title)).join(", ");
    note.textContent = `${names}: ${t("bu veri türlerinin bir dönemi yoktur; seçilen aralıktan bağımsız olarak tamamı iner.")}`;
  }
}

function downloadExport() {
  if (!exportSelection.size) return;
  const format = document.querySelector("#export-format").value;
  const bounds = exportPeriodBounds();
  const range = bounds ? `&since=${encodeURIComponent(bounds.since)}` : "";
  const chosen = [...exportSelection];
  const href = chosen.length === 1
    ? `/api/export/${chosen[0]}.${format}${range ? `?${range.slice(1)}` : ""}`
    : `/api/export/bundle?datasets=${chosen.join(",")}&file_format=${format}${range}`;
  const link = document.createElement("a");
  link.href = href;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

document.querySelectorAll("[data-export-group]").forEach(button => {
  button.addEventListener("click", () => {
    exportGroup = button.dataset.exportGroup;
    document.querySelectorAll("[data-export-group]").forEach(other => other.classList.toggle("is-active", other === button));
    renderExportList();
  });
});
document.querySelector("#export-search")?.addEventListener("input", renderExportList);
document.querySelector("#export-period")?.addEventListener("change", refreshExports);
document.querySelector("#export-download")?.addEventListener("click", downloadExport);

document.querySelector("#restore-backup").addEventListener("click", restoreBackup);

// The chosen file is only visible through the label now, and a restore button that can be
// pressed with nothing selected is a button that exists to show an error.
document.querySelector("#restore-file")?.addEventListener("change", event => {
  const file = event.target.files[0];
  const name = document.querySelector("#restore-file-name");
  const label = document.querySelector(".backup-file");
  name.textContent = file ? file.name : t("Dosya seçilmedi");
  label.classList.toggle("has-file", Boolean(file));
  document.querySelector("#restore-backup").disabled = !file;
});
document.querySelector("#settings-form").addEventListener("submit", saveSettings);
document.querySelectorAll("[data-settings-tab]").forEach(button =>
  button.addEventListener("click", () => showSettingsTab(button.dataset.settingsTab)));
document.querySelector("#settings-form").addEventListener("input", markSettingsDirty);
document.querySelector("#settings-form").addEventListener("change", markSettingsDirty);
document.querySelector("#password-form").addEventListener("submit", changePassword);
let guidanceSearchTimer = null;
document.querySelector("#guidance-search").addEventListener("input", () => {
  // The retriever runs on the server now, so a request per keystroke is wasteful.
  clearTimeout(guidanceSearchTimer);
  guidanceSearchTimer = setTimeout(renderGuidanceNotes, 180);
});
document.querySelector("#worker-form").addEventListener("submit", addWorker);
document.querySelector("#force-password-form").addEventListener("submit", submitForcedPassword);
document.querySelector("#force-password-logout").addEventListener("click", async () => {
  await fetch("/api/logout", {method: "POST"});
  window.location.replace("/login");
});
document.querySelector("#show-worker-form").addEventListener("click", () => {
  const form = document.querySelector("#worker-form");
  form.hidden = false;
  document.querySelector("#worker-display-name").focus();
});
document.querySelector("#cancel-worker-form").addEventListener("click", () => {
  const form = document.querySelector("#worker-form");
  form.reset();
  form.hidden = true;
});
document.querySelector("#worker-list").addEventListener("click", event => {
  const reset = event.target.closest("[data-worker-reset]");
  const toggle = event.target.closest("[data-worker-active]");
  if (reset) resetWorkerPassword(reset.dataset.workerReset);
  if (toggle) setWorkerActive(toggle.dataset.workerActive, toggle.dataset.active !== "true");
});
document.querySelector("#password-form").addEventListener("input", renderPasswordRules);
document.querySelector("#generate-recovery-code").addEventListener("click", generateRecoveryCode);
document.querySelector("#copy-recovery-code").addEventListener("click", copyRecoveryCode);
document.querySelector("#print-recovery-code").addEventListener("click", printRecoveryCode);
demoViewSwitch.addEventListener("click", toggleDemoView);
document.querySelector("#exit-worker-preview").addEventListener("click", () => setWorkerPreview(false));
document.querySelector("#preview-as-worker").addEventListener("click", () => setWorkerPreview(!workerPreview));
document.querySelector("#language-toggle").addEventListener("click", toggleLanguage);
document.querySelector("#reopen-guide").addEventListener("click", openGuide);
document.querySelector("#close-guide").addEventListener("click", closeGuide);
document.querySelector("#skip-guide").addEventListener("click", skipGuide);
document.querySelector("#guide-back").addEventListener("click", retreatGuide);
document.querySelector("#complete-guide").addEventListener("click", advanceGuide);
document.querySelector("#onboarding-dialog").addEventListener("keydown", event => {
  // Enter in a text field would otherwise do nothing here: there is no form to submit,
  // and the step's own button is what it is reaching for.
  if (event.key !== "Enter" || event.target.tagName === "BUTTON") return;
  event.preventDefault();
  advanceGuide();
});
loadSettings(true).finally(() => {
  if (!refreshTimer) refreshTimer = setInterval(refresh, refreshSeconds * 1000);
  refresh(); refreshContext(); refreshAlarms(); restoreViewFromHash();
  // A run started before this page load still needs watching, or the button would sit
  // on "generating" forever with nothing polling behind it.
  refreshReportGeneration().then(status => { if (status && status.running) watchReportGeneration(); });
});
setInterval(refreshContext, 300000);
const logoutButton = document.querySelector("#logout-button");
const currentUser = document.querySelector("#current-user");

fetch("/api/me").then((response) => response.json()).then((user) => {
  demoAvailable = Boolean(user.demo_mode);
  demoMode = demoAvailable;
  demoViewSwitch.hidden = !demoAvailable;
  renderDemoViewSwitch();
  currentRole = user.role || "owner";
  managesAccounts = Boolean(user.manages_accounts);
  document.querySelector("#workers-section").hidden = !managesAccounts;
  // Whether this browser's own language choice counts depends on the role, and the role
  // arrives after the settings do — so a field worker's preference is applied here rather
  // than in applySettings, which cannot yet know who is reading.
  const preferredLanguage = currentRole === "owner" ? null : localStorage.getItem("waggle-language");
  if (preferredLanguage && currentSettings && preferredLanguage !== currentLanguage) {
    applySettings({...currentSettings, language: preferredLanguage});
  }
  renderSettingsSidebar();
  document.body.classList.toggle("is-worker", currentRole === "worker");
  if (user.must_change_password) document.querySelector("#force-password-dialog").showModal();
  if (user.manages_accounts) refreshWorkers();
  currentDisplayName = user.display_name || user.username;
  currentUser.textContent = currentDisplayName;
  document.querySelector("#greeting-name").textContent = currentDisplayName;
});

document.querySelector("#profile-button").addEventListener("click", () => showView("settings", true));
document.querySelector("#overview-alert-button").addEventListener("click", () => showView("alarms", true));
document.querySelectorAll("[data-view-shortcut]").forEach(button => button.addEventListener("click", () => showView(button.dataset.viewShortcut, true)));

logoutButton.addEventListener("click", async () => {
  await fetch("/api/logout", {method: "POST"});
  window.location.replace("/login");
});
