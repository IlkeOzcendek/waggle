# Waggle sunum rehberi

Bu akış çalışan ürünü yaklaşık **4 dakikada** göstermeye yöneliktir. Önce problemi,
sonra canlı ürünü, en son teknik mimariyi anlatın. Modeli “tanı koyan sistem” değil,
**kovanın kendi normalini öğrenen erken uyarı sistemi** olarak tanımlayın.

## 1. Problem — 25 saniye

> Kovanlar çoğunlukla düzenli kontrolün zor olduğu alanlarda bulunuyor. Kraliçeyle
> veya koloni düzeniyle ilgili bir sorunun geç fark edilmesi ciddi kayba dönüşebilir.
> Waggle, her kovanın sağlıklı sesini öğrenir, kalıcı değişimi erken fark eder ve
> arıcıya kovanı kontrol etmesi için anlaşılır bir uyarı verir.

## 2. Genel bakış — 30 saniye

- Ana ekrandaki `NORMAL`, `WATCH` ve `ALARM` sayılarını gösterin.
- **Bahçe Kovanı**, **Orman Kovanı** ve **Çayır Kovanı** kartlarını gösterin.
- `H1`, `H2`, `H3` değerlerinin değişmeyen teknik kimlikler; görünen adların ise
  kullanıcı tarafından yönetilebildiğini söyleyin.
- Temel analiz, panel, alarm ve kayıt sisteminin internet olmadan çalıştığını belirtin.

## 3. Model ve alarm — 55 saniye

- **Çayır Kovanı (H3)** ayrıntısını açın.
- Kalıcı akustik değişimin önce `WATCH`, sonra `ALARM` oluşturduğunu gösterin.
- Anomali oranının kraliçe kaybı olasılığı olmadığını açıklayın: model, sesin
  kovanın öğrendiği sağlıklı profilden ne ölçüde uzaklaştığını izler.
- Akışı tek cümlede özetleyin:

> Telefon veya sensörden gelen WAV kaydı 21 akustik özelliğe dönüştürülür, ONNX
> modeli sonucu üretir, ortak olay sözleşmesiyle panele gönderilir ve SQLite'a kaydedilir.

- **Alarmlar** ekranını açın. Alarmın ancak fiziksel kontrolden sonra “kontrol edildi”
  olarak işaretlendiğini ve geçmişin silinmediğini gösterin.

## 4. Yeni kovanın öğrenilmesi — 55 saniye

- **Kovanlarım → Yeni kovan ekle** yolunu gösterin.
- **Cihazlar ve model** bölümünden telefonu yeni kovana bağlayın.
- Üç şartın ekranda kontrol listesi olarak durduğunu gösterin. Özellikle gün şartını
  okuyun: takvim günü sayılır, aynı gün kırk dosya göndermek tek gün ekler.
- Kayıt göndermenin iki yolu olduğunu gösterin: birden fazla dosya seçmek ya da
  **Cihazdan canlı dinle** ile mikrofondan kaydetmek. Kayıtlar sırayla gönderilir.
- Durum geçişini açıklayın: `Cihaz bekleniyor → Öğrenme devam ediyor → İzleme etkin`.
- Profilin aynı kovan ve mikrofonla alınan **42 sağlıklı kayıt**, **14 farklı gün** ve
  **4 güvenilir saha doğrulaması** istediğini belirtin.
- Uygulamanın başlangıçta ve en fazla dört günde bir kraliçe/yavru/koloni kontrolü
  sorduğunu; “emin değilim” yanıtının eğitime katılmadığını söyleyin.
- Ham sesin özellik çıkarımından sonra silindiğini; yalnızca kompakt öğrenme
  özelliklerinin SQLite'ta tutulduğunu belirtin.
- Eşik tamamlandığında kişisel profilin otomatik oluşturulduğunu, ONNX karar
  eşitliği doğrulanmadan alarm üretiminin açılmadığını vurgulayın.

## 4b. Ekip ve hesaplar — 35 saniye

- **Ayarlar → Ekip** bölümünde bir çalışan hesabı açın; geçici parolayı sizin
  ilettiğinizi, çalışanın ilk girişte kendi parolasını belirlemeden hiçbir işlem
  yapamadığını söyleyin. Bu olmadan “bu kontrolü kim yaptı” kaydı kimseyi göstermez.
- **Çalışan gözüyle bak** ile kısıtlı paneli gösterin: çalışan kayıt gönderir, saha
  kontrolü girer, alarmın fiziksel kontrolünü tamamlar; kovan silemez, cihaz bağlayamaz,
  ayarlara ve yedeğe dokunamaz. Bu kısıt sunucuda zorlanır, sadece ekranda gizlenmez.
- Bir alarmı kapatıp kaydın **kimin kontrol ettiğini** yazdığını gösterin.
- Çalışanı devre dışı bıraktığınızda açık oturumunun anında kapandığını söyleyin.
- Parola kurtarmanın üç yolu olduğunu belirtin: kurtarma kodu, sahibin çalışana yeni
  parola vermesi, ya da panelin çalıştığı bilgisayarda `tools.reset_password`. Yerel ve
  çevrimdışı bir panelde e-postayla sıfırlama yoktur.

## 5. Yerel yapay zekâ raporu — 35 saniye

- **Raporlar** bölümünde Türkçe raporu gösterin, ardından `TR / EN` ile İngilizceye geçin.
- Phi modelinin **Foundry Local** üzerinde cihazda çalıştığını söyleyin.
- Küçük yerel RAG katmanının olayla ilgili, sürüm kontrollü güvenlik bilgisini seçtiğini;
  ses kayıtlarının bilgi tabanına eklenmediğini açıklayın.
- Haftalık agent'ın son yedi günlük olayları toplayıp Türkçe ve İngilizce raporları
  otomatik oluşturduğunu ve aynı SQLite veritabanına kaydettiğini belirtin.
- Model yanıtı geçersizse güvenli deterministik raporun devreye girdiğini söyleyin.

## 6. Kapanış — 20 saniye

> Waggle yalnızca bir ses sınıflandırıcısı değil. Kovana özel öğrenme, ONNX tabanlı
> yerel analiz, SQLite kayıtları, Foundry Local, güvenli RAG ve iki dilli raporlamayı
> tek bir çevrimdışı akışta birleştiren uçtan uca bir erken uyarı sistemidir.

## Gösterim sırası

1. Genel Bakış
2. H3 ayrıntısı
3. Alarmlar
4. Kovanlarım → yeni kovan → cihaz ve öğrenme
5. Raporlar → Türkçe/İngilizce
6. Sistem Durumu

## Beklenen sorular

**“Kraliçe öldü” diyebiliyor musunuz?** Hayır. Sistem kraliçe kaybıyla uyumlu
olabilecek kalıcı akustik değişimi erken fark eder. Alarm kesin tanı değildir;
kovanın ve kraliçenin fiziksel olarak kontrol edilmesini ister.

**İnternet kesilirse ne olur?** Ses analizi, ONNX çıkarımı, olay kaydı, SQLite,
panel ve Foundry Local yerel çalışır. Gönderilemeyen olaylar cihaz tarafında kuyruğa
alınır. Hava durumu isteğe bağlıdır ve varsayılan olarak kapalıdır.

**Model yeni bir kovanı nasıl öğreniyor?** Aynı kovan ve mikrofonla farklı günlerde
sağlıklı kayıtlar toplanır. 42 kayıt, 14 gün ve 4 saha doğrulaması tamamlanana kadar
sistem alarm üretmez. Sonra kovana özel profil oluşturulur ve ONNX eşitliği doğrulanır.

**Kayıt yanlışlıkla hasta kovandan alınırsa ne olur?** Uygulama düzenli saha sağlık
doğrulaması ister. Kullanıcı emin değilse kayıt öğrenmeye alınmaz. Bu mekanizma riski
azaltır; gerçek saha doğrulaması yine gereklidir.

**Ham ses saklanıyor mu?** Hayır. Yüklenen kayıt 21 akustik özelliğe dönüştürüldükten
sonra silinir. Özellikler, olaylar, raporlar ve ayarlar yerel SQLite'ta tutulur.

**RAG ne işe yarıyor?** RAG, Phi'ye yalnızca olayla ilgili gözden geçirilmiş yerel
operasyon bilgisini verir. Böylece rapor, alarmı kesin teşhis gibi sunmaz ve doğru
fiziksel kontrol adımlarına bağlı kalır.

**Foundry Local çalışmazsa ne olur?** Alarm akışı durmaz. Doğrulanmış deterministik
rapor devreye girer ve kullanılan üretici bilgisi SQLite'ta saklanır.

**Sonuçlar gerçek mi?** Evet; demo gerçek ONNX çıkarım hattını ve saklanan olayları
kullanır. Mevcut en güçlü kişisel-kovan testi %94,17 doğruluk ve %100 bozulma yakalama
vermiştir. Bu sonuç kontrollü veri tekrarına aittir; saha başarısı olarak sunulmamalıdır.

**Birden fazla kişi kullanabilir mi?** Evet. Arıcı, ekibine çalışan hesabı açar.
Çalışan saha işini yapar — kayıt gönderir, saha kontrolü girer, alarmı kapatır — ama
kovan, cihaz, ayar ve yedeğe dokunamaz. Her işlem hesabın adıyla kaydedilir, böylece
hangi kontrolü kimin yaptığı belli olur.

**Parolamı unutursam?** Ayarlardan tek kullanımlık bir kurtarma kodu üretirsiniz ve
giriş ekranındaki **Parolamı unuttum** ile yeni parola belirlersiniz. Kod bir kez
gösterilir, bir kez çalışır ve veritabanında yalnızca özeti tutulur. Kod da yoksa,
panelin çalıştığı bilgisayarda `python -m tools.reset_password` komutu vardır —
o makineye erişebilen kişi zaten veritabanına erişebiliyor.

**Panel ile model birbirine bağımlı mı?** Hayır. Model ve panel `CONTRACT.md` içindeki
aynı olay JSON'u üzerinden haberleşir; bileşenler ayrı ayrı geliştirilebilir.

## Sunum öncesi son kontrol

- `python tools/run_demo.py --foundry` komutunu internet kapalıyken bir kez çalıştırın.
- H1/H2/H3 sayılarının sırasıyla `NORMAL/WATCH/ALARM` olduğunu doğrulayın.
- Türkçe ve İngilizce raporların açıldığını kontrol edin.
- Yeni kovan ve cihaz ekranının öğrenme ilerlemesini ve üç şartın kontrol listesini
  gösterdiğini doğrulayın.
- Çoklu dosya göndermeyi bir kez deneyin; canlı mikrofon kaydını **sunum yapacağınız
  bilgisayarda** deneyin (telefonda `--lan` üzerinden mikrofon açılmaz).
- Rapor PDF indirmeyi bir kez deneyin; `reportlab` kurulu değilse burada patlar.
- Sunucuyu kod değişikliğinden sonra yeniden başlattığınızdan emin olun.
- Ekran kaydı için bildirimleri kapatın ve tarayıcı yakınlaştırmasını `%100` yapın.
