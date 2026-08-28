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
- Kalıcı akustik değişimin `WATCH` ve ardından `ALARM` durumuna geçtiğini gösterin.
- Grafikteki anomali oranının teşhis olasılığı olmadığını; modelin kovanın öğrendiği
  normal sesten ne kadar kalıcı biçimde uzaklaşıldığını izlediğini açıklayın.
- Akışı tek cümleyle anlatın:

> Ses kaydı ONNX modeliyle cihazda değerlendirilir, sonuç ortak olay sözleşmesiyle
> panele gelir, SQLite'a kaydedilir ve Foundry Local/Phi tarafından arıcıya uygun
> bir rapora dönüştürülür.

- Bunun kesin teşhis değil, fiziksel kontrol gerektiren bir karar desteği olduğunu
  özellikle söyleyin.

## 4. Alarm ve takip (45 saniye)

- **Alarmlar** bölümünde H3 alarmını açın.
- Fiziksel kontrol sonrasında alarmın çözüldü olarak işaretlenebildiğini gösterin.
- Geçmişin silinmediğini ve izlenebilirlik için saklandığını açıklayın.

## 5. Yönetim ve rapor (45 saniye)

- **Kovanlarım** bölümünde yeni bir kovanın kolayca eklenebildiğini gösterin.
- **Raporlar** bölümünde haftalık özet ve önerileri gösterin.
- `TR / EN` düğmesiyle paneli İngilizceye geçirip Phi raporunun iki dili de
  desteklediğini gösterin.
- Hava durumunun isteğe bağlı çevrimiçi özellik olduğunu; varsayılan olarak kapalı
  kaldığını ve açık izin olmadan konum paylaşılmadığını belirtin.

## 6. Kapanış (15 saniye)

> Waggle yalnızca bir sınıflandırma modeli değil; çevrimdışı çalışabilen, sonucu
> saklayan, alarm üreten ve arıcının kararını kolaylaştıran uçtan uca bir sistemdir.

## Beklenen sorular

**İnternet kesilirse ne olur?**  Temel ses analizi, olay kaydı ve panel yerel ağda
çalışır. Gönderilemeyen olaylar cihaz tarafında kuyruğa alınır. Çevrimiçi hava
durumu zaten varsayılan olarak kapalıdır.

**Model yanlış sonuç verebilir mi?**  Evet. Anomali oranı bir teşhis olasılığı
değildir; ürün kesin teşhis yerine erken uyarı ve fiziksel kontrol önerisi sunar.

**Rapor internetten mi geliyor?**  Hayır. Phi modeli Foundry Local üzerinde cihazda
çalışır. Model geçersiz bir yapı üretirse güvenli ve kayıt altına alınan deterministik
yedek rapor kullanılır.

**Yeni kovan eklenebilir mi?**  Evet. Kullanıcı dostu ad ve konum girilir; teknik
kimlik sistem tarafından otomatik atanır.

**Veriler nerede tutuluyor?**  Olaylar ve kullanıcı ayarları cihazdaki yerel SQLite
veritabanında tutulur ve yedeklenebilir.

**Gerçek model bağlandığında panel değişecek mi?**  Hayır. Model ve panel
`CONTRACT.md` içindeki aynı olay JSON'u üzerinden bağımsız çalışır.
