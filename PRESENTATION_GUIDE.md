# Waggle sunum rehberi

Bu rehber, çalışan ürünü yaklaşık 4 dakikada anlaşılır biçimde göstermek için
hazırlanmıştır. Teknik ayrıntıya geçmeden önce çözülen problemi anlatın.

## 1. Problem (30 saniye)

> Kovanlar çoğunlukla internetin zayıf olduğu uzak alanlarda bulunuyor. Ana arı
> kaybının geç fark edilmesi koloni sağlığını riske atıyor. Waggle, kovan sesini
> sahada dinleyip yapay zekâ ile değerlendiriyor ve arıcıya anlaşılır bir uyarı
> veriyor.

## 2. Ana ekran (45 saniye)

- Genel durum sayılarını ve kullanıcı dostu kovan adlarını gösterin.
- `H1`, `H2`, `H3` değerlerinin cihazların değişmeyen teknik kimlikleri olduğunu;
  kullanıcının ise **Bahçe Kovanı** gibi anlaşılır adlar gördüğünü açıklayın.
- Sistemin internet bağlantısı olmadan temel izleme, kayıt ve alarm üretmeye
  devam ettiğini belirtin.

## 3. Yapay zekâ sonucu (60 saniye)

- **Deneme Kovanı (H3)** ayrıntısını açın.
- `%91 ana arı kaybı şüphesi` sonucunu ve güven grafiğini gösterin.
- Akışı tek cümleyle anlatın:

> Ses kaydı cihazda değerlendirilir, sonuç ortak olay sözleşmesiyle panele gelir,
> SQLite'a kaydedilir ve kullanıcıya alarm olarak gösterilir.

- Bunun kesin teşhis değil, fiziksel kontrol gerektiren bir karar desteği olduğunu
  özellikle söyleyin.

## 4. Alarm ve takip (45 saniye)

- **Alarmlar** bölümünde H3 alarmını açın.
- Fiziksel kontrol sonrasında alarmın çözüldü olarak işaretlenebildiğini gösterin.
- Geçmişin silinmediğini ve izlenebilirlik için saklandığını açıklayın.

## 5. Yönetim ve rapor (45 saniye)

- **Kovanlarım** bölümünde yeni bir kovanın kolayca eklenebildiğini gösterin.
- **Raporlar** bölümünde haftalık özet ve önerileri gösterin.
- Hava durumunun isteğe bağlı çevrimiçi özellik olduğunu; varsayılan olarak kapalı
  kaldığını ve açık izin olmadan konum paylaşılmadığını belirtin.

## 6. Kapanış (15 saniye)

> Waggle yalnızca bir sınıflandırma modeli değil; çevrimdışı çalışabilen, sonucu
> saklayan, alarm üreten ve arıcının kararını kolaylaştıran uçtan uca bir sistemdir.

## Beklenen sorular

**İnternet kesilirse ne olur?**  Temel ses analizi, olay kaydı ve panel yerel ağda
çalışır. Gönderilemeyen olaylar cihaz tarafında kuyruğa alınır. Çevrimiçi hava
durumu zaten varsayılan olarak kapalıdır.

**Model yanlış sonuç verebilir mi?**  Evet. Güven değeri kullanıcıya gösterilir;
ürün kesin teşhis yerine erken uyarı ve fiziksel kontrol önerisi sunar.

**Yeni kovan eklenebilir mi?**  Evet. Kullanıcı dostu ad ve konum girilir; teknik
kimlik sistem tarafından otomatik atanır.

**Veriler nerede tutuluyor?**  Olaylar ve kullanıcı ayarları cihazdaki yerel SQLite
veritabanında tutulur ve yedeklenebilir.

**Gerçek model bağlandığında panel değişecek mi?**  Hayır. Model ve panel
`CONTRACT.md` içindeki aynı olay JSON'u üzerinden bağımsız çalışır.
