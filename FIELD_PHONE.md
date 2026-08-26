# Eski bir telefonu yerel Waggle ekranı olarak kullanma

Bu özellik ilk aşamada telefonu ayrı bir sensöre dönüştürmez. Telefon, bilgisayarda
çalışan Waggle panelini aynı yerel ağ üzerinden gösteren taşınabilir bir ekran olur.
İnternet bağlantısı gerekmez; bilgisayar ve telefonun birbirini görebildiği bir
Wi-Fi ağı veya kişisel erişim noktası yeterlidir.

## Başlatma

Bilgisayarda proje klasöründe:

```bash
source .venv/bin/activate
python tools/run_demo.py --lan
```

Terminalde `Telefon adresi` altında `http://192.168...:8000` biçiminde bir adres
görünür. Bu adresi aynı ağa bağlı Android telefonun tarayıcısında açın ve demo
hesabıyla giriş yapın.

## Bağlantı kontrolü

1. Bilgisayar ve telefonun aynı Wi-Fi ağına bağlı olduğunu kontrol edin.
2. VPN'i iki cihazda da kapatın.
3. macOS güvenlik duvarı sorarsa Python için gelen bağlantıya izin verin.
4. Terminalde gösterilen adresi `127.0.0.1` ile değiştirmeyin. Bu adres telefonda
   telefonun kendisini ifade eder.
5. Sayfa açılmazsa iki cihazı internet gerektirmeyen aynı telefon erişim noktasına
   bağlayıp yeniden deneyin.

## Güvenlik

- `--lan` yalnızca güvendiğiniz özel ağlarda kullanılmalıdır.
- Demo parolası gerçek saha kurulumunda kullanılmamalıdır.
- Gerçek kullanımda `.env` içindeki yönetici parolası, cihaz anahtarı ve oturum
  anahtarı güçlü ve benzersiz değerlerle değiştirilmelidir.
- Bu ilk sürüm şifrelenmemiş yerel HTTP kullanır; halka açık ağlarda çalıştırmayın.

## Sonraki geliştirme

Model entegrasyonu tamamlandıktan sonra aynı telefon ekranına kritik olaylar için
yerel tarayıcı bildirimi ve ana ekrana eklenebilen uygulama görünümü eklenebilir.
Bu geliştirme, mevcut olay sözleşmesini veya panel veritabanını değiştirmez.
