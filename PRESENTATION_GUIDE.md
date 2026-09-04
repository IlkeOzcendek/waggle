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

- Kararı **hangi model dosyasının** verdiğinin olayla birlikte saklandığını söyleyin.
  Rapor, PDF ve dışa aktarım bu bilgiyi taşır; bir kaydın hangi profille ölçüldüğü
  sonradan sorulabilir bir sorudur.
- **Alarmlar** ekranını açın. Alarmın ancak fiziksel kontrolden sonra “kontrol edildi”
  olarak işaretlendiğini ve geçmişin silinmediğini gösterin.
- Alarm kartının altındaki **YEREL KILAVUZ** bloğunu gösterin: o alarma uyan gözden
  geçirilmiş notlar, kimlikleriyle. Aynı şey telemetri tablosunda da var — bir `WATCH`
  satırındaki **Kılavuz** düğmesine basın. Bunun için modele hiç gidilmez; seçim yerel
  ve deterministiktir, yani yerel model kapalıyken bile çalışır. `WATCH`, “müdahale
  etsem mi?” sorusunun açık olduğu andır; notların orada olmasının sebebi bu.

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
- Parola değişince eski parolayla açılmış **diğer** oturumların da kapandığını ekleyin —
  telefon, ödünç alınmış bilgisayar. Parolayı değiştirdiğiniz oturum açık kalır. Sorulursa:
  oturumlar imzalı jetonlardır, sunucuda kayıtları yoktur; jeton parolanın izini taşır ve
  parola değişince iz tutmaz. Kurtarma kodu da aynı şekilde davranır — zaten sebebi budur.
- Parola kurtarmanın üç yolu olduğunu belirtin: kurtarma kodu, sahibin çalışana yeni
  parola vermesi, ya da panelin çalıştığı bilgisayarda `tools.reset_password`. Yerel ve
  çevrimdışı bir panelde e-postayla sıfırlama yoktur.

## 5. Yerel yapay zekâ raporu — 35 saniye

- **Raporlar** bölümünde Türkçe raporu gösterin, ardından `TR / EN` ile İngilizceye geçin.
- Ölçüm şeridindeki **Ölçüm modeli** satırını gösterin: dönemin olaylarını hangi ONNX
  profilinin ölçtüğü orada yazar. Dönemin olayları bir model adı taşımıyorsa — çok eski
  kayıtlar ya da bu sürümden önce üretilmiş olaylar — satır hiç çıkmaz; uydurmaz. Model
  destekli bir raporda sağ
  sütundaki köken satırı zinciri tek bakışta verir — `ONNX → SQLite → RAG → Foundry Local`.
  Raporu yazan model zincirin sonu; başı ölçümü yapan modeldir ve panel ikisini birbirine
  karıştırmıyor. (Deterministik raporda o satır çıkmaz, çünkü ortada bir model yoktur.)
- Phi modelinin **Foundry Local** üzerinde cihazda çalıştığını söyleyin.
- Yerel kılavuz tabanının **28 gözden geçirilmiş nottan** oluştuğunu, modele yalnızca
  döneme uyanların verildiğini; ses kayıtlarının bu tabana hiç girmediğini açıklayın.
- Seçimin durum etiketine değil **döneme ait olgulara** bakarak yapıldığını gösterin:
  aykırı ses oranı, ardışık pencere uzunluğu, kaç kovanın aynı anda değiştiği ve **ay**.
  Mayıstaki bir alarm oğul hazırlığını, aynı alarm aralıkta kış kümesini getirir; mevsimsel
  not her zaman bir yer alır.
- Sağ sütundaki **“Bu değerlendirme neye dayanıyor”** kartını açın: raporun dayandığı
  notlar kimlikleri ve metinleriyle orada. Kaynak sayısı bir iddiadır, notların kendisi kanıt.
- **MODEL KARARI** panelini gösterin. Modelin döndürdüğü yapısal karar orada durur:
  öncelik, tespit edilen örüntü, kraliçe kaybıyla uyumluluk, fiziksel kontrolün gerekip
  gerekmediği ve önerilen eylem kodları. Özet metni modelin *anlattığı* şeydir; bu panel
  modelin *karar verdiği* şeydir — biri diğerinden sapıyorsa bu ekranda görülür.
- **Yeni rapor üret** düğmesine basın: rapor sunuda, izleyicinin önünde, cihazda üretilir.
  Foundry Local yalnızca haftalık agent'ın kullandığı bir arka plan işi değil, panelin
  içinden çağrılan bir parçası. (`WAGGLE_LLM_ENABLED=1` gerekir; kapalıysa düğme
  deterministik raporu üretir ve panel bunu söyler.)
- **PDF indir** deyip açın: model kararı, çapraz doğrulama sonucu, dayandığı kılavuz
  notlarının metni ve alarmı kimin kontrol ettiği PDF'te de var. Paylaşılan belge
  ekranda gösterilenin arkasındaki gerekçeyi de taşır.
- **Ayarlar → Yerel kılavuz** bölümünü açın: 28 notun tamamı, etiketleriyle ve arama
  kutusuyla. Bilgi tabanı bir kara kutu değil, okunabilir ve sürüm kontrollü bir metin.
  Arama kutusu düz metin eşleştirmesi değil, raporun dayandığı **aynı arama katmanını**
  çalıştırır: “varroa” yazın, sonbahar notu başa gelsin. Tabanı incelediğiniz ekran,
  açıklamak için var olduğu sıralamayı gösteriyor.
- Haftalık agent'ın son yedi günlük olayları toplayıp Türkçe ve İngilizce raporları
  otomatik oluşturduğunu ve aynı SQLite veritabanına kaydettiğini belirtin.
- Model yanıtı geçersizse güvenli deterministik raporun devreye girdiğini söyleyin. Kovan
  uyduran ya da teşhis koyan metin reddedilip şablona dönülür — bu, panelde göründüğü için
  gösterilebilir bir güvence.

## 5b. İki modelin çapraz doğrulaması — 20 saniye

*(Yalnızca `WAGGLE_CROSS_CHECK_MODEL` ayarlıysa gösterin.)*

- **Hazırlayan** kutusunun altındaki satırı gösterin: yeşilse iki yerel model aynı kararda
  birleşmiş, amberse farklı karar vermişler ve **temkinli olan** seçilmiş.
- Bu satır, raporun sakladığı kararın kendisinden okunur — üretici metninden değil. Metni
  modelin yazdığı ama ikinci modelin bulunmadığı bir raporda panel doğru cümleyi kurar:
  “tek yerel modelin kararı; çapraz doğrulama yapılmadı”.
- Neden temkinli olanın seçildiğini söyleyin: bir alarmı kaçırmak koloniye mal olur,
  fazladan kontrol istemek yalnızca bir yürüyüşe.
- Çapraz doğrulamanın raporu asla bozamayacağını belirtin — ikinci model yoksa ya da
  çökerse birinci değerlendirme olduğu gibi kalır.
- Somut örnek verebilirsiniz, bu makinede ölçüldü: yükselen ama henüz alarm olmayan bir
  haftada `phi-3.5-mini` *rutin* dedi, `qwen2.5-1.5b` *izleme* dedi ve temkinli olan seçildi.
  İkinci model, birincisinin gelişen bir değişimi hafife almasını yakaladı — sebebi tam
  olarak bu. Alarmlı bir haftada ikinci modelin cevabı reddedilebilir; orada zaten
  deterministik kural önceliği *acil*e sabitliyor, yani kaybedilen bir şey yok.
- **Rapor üretimi bu donanımda üç ilâ beş dakika sürüyor.** Düğmeye Raporlar bölümüne
  *girerken* basın ve model kararı, kılavuz kartı ve dışa aktarma bölümünü anlatırken
  çalışsın. Başında bekleyip sessiz kalmayın.
- Araç desteği sorulursa: ajanın `period_overview`, `hive_history` ve `look_up_guidance`
  araçları var, hepsi salt okuma. Ama araç çağırma **modelin yeteneği**; Foundry bunu model
  başına bildiriyor ve panel araçları yalnızca destekleyen modele ekliyor. Varsayılan
  `phi-3.5-mini` desteklemiyor. “Araç desteği modele göre otomatik açılıyor” deyin,
  “ajan araç kullanıyor” demeyin.

## 5c. Dışa aktarma — 15 saniye

- **Dışa Aktar** bölümünde sekiz veri kümesi var. **Saha doğrulamaları** (hangi kovanı kim,
  ne zaman, ne bulduğuyla kontrol etti), **Yerel kılavuz tabanı** (modele verilen 28 not),
  **Öğrenme kayıtları** ve **Cihazlar**.
- Öğrenme iddiası sorgulanırsa **Öğrenme kayıtları**nı açın: her kayıt bir satır, hangi
  cihazdan geldiği, hangi takvim gününe düştüğü ve sağlıklı doğrulanıp doğrulanmadığıyla.
  42 kayıt / 14 gün eşiğinin saydığı şey tam olarak budur; kovan kartındaki yüzde bu
  dosyadan yeniden hesaplanabilir. Ses dosyaları içinde değil — öznitelik çıkarımından
  sonra siliniyor — öznitelik vektörleri de değil.
- Söylenecek cümle: sistemin dayandığı bilgi de, sistemin verdiği kararlar da,
  insanların yaptığı kontroller de tek tuşla dışarı alınabilir. Kapalı bir kutu değil.
- Rapor dışa aktarımı artık modelin kararını da taşıyor: öncelik, örüntü, kontrol
  gerekliliği ve çapraz doğrulama sonucu sütun olarak orada.

## 5d. Sistem durumu — 15 saniye

- **Sistem Durumu** bölümünde **Akustik model (ONNX)** kartını gösterin. Panel burada
  modelin gerçekten yerinde olup olmadığını kontrol eder: paketlenmiş model dosyası,
  izlenen her kovanın kendi profil dosyası ve dönüşümün doğrulanmış olması.
- Karttaki cümleyi okuyun: `referans modelde 5400 satırda karar eşleşmesi doğrulandı`.
  Yani ONNX'e dönüştürülen model, dönüştürüldüğü joblib modelden **tek bir kararda bile**
  ayrılmıyor. Sayı `results/mendeley_onnx_parity.json` dosyasından geliyor; sürüm
  kontrolünde duran, açılıp okunabilen bir kanıt.
- Kovana özel profillerde aynı karşılaştırma eğitim anında yapılır, profille birlikte
  saklanır ve kartta `N/M kovan profili karar eşleşmesiyle doğrulandı` olarak görünür.
  Karşılaştırma başarısız olursa profil zaten yayımlanmaz — sistem ancak eşitliği
  doğrulanmış bir modelle izlemeye geçer.
- Bir model dosyası silinmişse kart uyarıya döner ve hangi kovanın dosyasının eksik
  olduğunu adıyla söyler. Daha önce bu bileşen yalnızca son olayın ne kadar taze
  olduğuna bakıyordu.

## 6. Kapanış — 20 saniye

> Waggle yalnızca bir ses sınıflandırıcısı değil. Kovana özel öğrenme, ONNX tabanlı
> yerel analiz, SQLite kayıtları, Foundry Local, güvenli RAG ve iki dilli raporlamayı
> tek bir çevrimdışı akışta birleştiren uçtan uca bir erken uyarı sistemidir.

## Gösterim sırası

1. Genel Bakış
2. H3 ayrıntısı
3. Alarmlar → alarm kartındaki yerel kılavuz notları
4. Kovanlarım → yeni kovan → cihaz ve öğrenme
5. Raporlar → Türkçe/İngilizce → Ölçüm modeli → Model kararı → Yeni rapor üret → PDF
6. Dışa Aktar → saha doğrulamaları ve kılavuz tabanı
7. Sistem Durumu → Akustik model (ONNX)
8. Ayarlar → Yerel kılavuz (sorulursa)

## Beklenen sorular

**“Kraliçe öldü” diyebiliyor musunuz?** Hayır. Sistem kraliçe kaybıyla uyumlu
olabilecek kalıcı akustik değişimi erken fark eder. Alarm kesin tanı değildir;
kovanın ve kraliçenin fiziksel olarak kontrol edilmesini ister.

**İnternet kesilirse ne olur?** Ses analizi, ONNX çıkarımı, olay kaydı, SQLite,
panel ve Foundry Local yerel çalışır. Gönderilemeyen olaylar cihaz tarafında kuyruğa
alınır. Hava durumu isteğe bağlıdır ve varsayılan olarak kapalıdır.

**Model yeni bir kovanı nasıl öğreniyor?** Aynı kovan ve mikrofonla farklı günlerde
sağlıklı kayıtlar toplanır. 42 kayıt, 14 gün ve 4 saha doğrulaması tamamlanana kadar
sistem alarm üretmez. Sonra kovana özel profil oluşturulur ve ONNX eşitliği doğrulanır;
bu doğrulama profille birlikte saklanır ve Sistem Durumu ekranında görünür.

**Kayıt yanlışlıkla hasta kovandan alınırsa ne olur?** Uygulama düzenli saha sağlık
doğrulaması ister. Kullanıcı emin değilse kayıt öğrenmeye alınmaz. Bu mekanizma riski
azaltır; gerçek saha doğrulaması yine gereklidir.

**Ham ses saklanıyor mu?** Hayır. Yüklenen kayıt 21 akustik özelliğe dönüştürüldükten
sonra silinir. Özellikler, olaylar, raporlar ve ayarlar yerel SQLite'ta tutulur.

**RAG ne işe yarıyor?** RAG, Phi'ye yalnızca olayla ilgili gözden geçirilmiş yerel
operasyon bilgisini verir. Böylece rapor, alarmı kesin teşhis gibi sunmaz ve doğru
fiziksel kontrol adımlarına bağlı kalır. Aynı arama katmanı raporun dışında da çalışır:
alarm kartlarında, `WATCH` telemetri satırlarında ve kılavuz aramasında — bunların
hiçbirinde modele gidilmez.

**ONNX'e dönüştürürken kararlar değişmiş olabilir mi?** Dönüştürme aynı veriyi hem joblib
hem ONNX modele verir, kararları karşılaştırır ve tek bir fark bulursa modeli yazmayı
reddeder. Referans modelde 5400 satırda sıfır fark ölçüldü; kovana özel profillerde aynı
kontrol eğitim anında yapılır ve sonucu profille saklanır. İkisi de **Sistem Durumu**
ekranında yazılı, yani sözle değil ekranla cevaplanabilir bir soru.

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

**Rapor neye dayanıyor, uyduruyor mu?** Modele yalnızca döneme uyan gözden geçirilmiş
notlar veriliyor ve çıktısı kullanılmadan önce denetleniyor: öncelik üç izinli değerden
biri olmak zorunda, olmayan bir kovandan söz eden ya da teşhis koyan metin reddedilip
deterministik şablona dönülüyor. Raporun dayandığı notlar panelde metinleriyle görünüyor.

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
- **Sistem Durumu → Akustik model (ONNX)** kartının yeşil olduğunu doğrulayın. `results/`
  klasörü ya da parite raporu eksikse uyarı burada çıkar, sunum sırasında değil.
- Sunucuyu kod değişikliğinden sonra yeniden başlattığınızdan emin olun.
- **Kullanıcı adını kayıttaki hâliyle yazın.** Adlar harfi harfine eşleşir: `İlke`, `ilke`
  ve `Ilke` üç ayrı hesaptır. Hangi adların var olduğunu görmek için `python -m
  tools.reset_password` komutunu argümansız çalıştırın; hiçbir şeyi değiştirmez.
- Ekran kaydı için bildirimleri kapatın ve tarayıcı yakınlaştırmasını `%100` yapın.
