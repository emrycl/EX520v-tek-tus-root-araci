# EX520v Tek Tuş Root Aracı

EX520v modemlerde kalıcı UID 0 erişimi sağlayan, kurulumu ve doğrulamayı tek
akışta tamamlayan çok platformlu bir araçtır. Cihazı ve firmware sürümünü
kurulumdan önce denetler; uygun profili otomatik seçer ve gerekli dosyaları
yalnız yerel ağ üzerinden modeme aktarır.

## Önemli uyarı

Bu proje yalnızca sahibi olduğunuz veya yönetmek için açık izin aldığınız
cihazlarda kullanılmalıdır. Yetkisiz erişim, hizmet engelleme, ağlara izinsiz
müdahale veya diğer yasa dışı işlemler kullanıcının sorumluluğundadır.

Firmware üzerinde değişiklik yapmak garanti ve destek koşullarını
etkileyebilir. Başlamadan önce modem ayarlarınızı yedekleyin.

## Özellikler

- TCP/2222 üzerinden anahtar tabanlı UID 0 SSH
- TCP/2323 üzerinden parolalı UID 0 Telnet
- Token korumalı yerel root API
- Modem yeniden başlatıldığında otomatik çalışan kalıcı kurulum
- Root servislerini yerel ağla sınırlayan güvenlik duvarı kuralları
- TR-069 yönetim portu için erişim kilidi
- Her modem için ayrı parola, API tokenı, SSH anahtarı ve `known_hosts` kaydı
- Kurulum öncesi model, firmware ve dosya bütünlüğü doğrulaması
- Doğrulanmış yedek üzerinden güvenli kaldırma

Tam firmware profilinde ayrıca stok web paneli için gerçek `root` hesabı,
backend erişimi, Port Mirror, Paket Yakalama, CWMP ve Sistem Araçları sayfaları
açılır. Araç yeni bir web arayüzü kurmaz; firmware içinde bulunan stok sayfaları
ve backend nesnelerini kullanır.

## Desteklenen cihaz ve firmware sürümleri

| Model | Firmware | Profil | Sağlanan erişim |
| --- | --- | --- | --- |
| EX520v | `EX520v_260514` | Tam | SSH, Telnet, root API, root web paneli ve stok tanılama sayfaları |
| EX520v | `EX520v-v1.0_250522` | Çekirdek root | SSH, Telnet ve root API |
| EX520v | `EX520v-v1.0_250120` | Çekirdek root | SSH, Telnet ve root API |

Tüm EX520v donanım revizyonları kabul edilir. Araç model ve firmware sürümünü
kurulum başlamadan doğrular; desteklenmeyen bir cihazda modeme dosya göndermez.

Eski firmware sürümlerinde sürüme bağımlı web paneli bellek yamaları güvenlik
amacıyla uygulanmaz. Stok yönetici hesabı korunur; kalıcı UID 0 SSH, Telnet,
root API ve TR-069 kilidi kurulmaya devam eder.

## Platform durumu

| Platform | Durum |
| --- | --- |
| Linux | Fiziksel modem üzerinde test edildi |
| Windows 10 | Desteklenen üç firmware sürümüyle fiziksel modem üzerinde test edildi |
| macOS | Başlatıcı hazır; fiziksel cihazda uçtan uca test edilmedi |

Windows başlatıcısının eksik bağımlılıkları temiz bir sisteme otomatik kurma
akışı henüz uçtan uca test edilmemiştir.

## Gereksinimler

- Modemin yerel ağına Ethernet veya Wi-Fi bağlantısı
- `http://192.168.1.1/` adresindeki modem paneline erişim
- Eksik sistem bileşenlerinin ilk kurulumu için internet bağlantısı

Başlatıcı Python, Chrome/Chromium ve OpenSSH gereksinimlerini denetler. Linux'ta
ayrıca geçici aktarım izni için `iptables` gerekir. Eksikler desteklenen
sistemlerde şu kaynaklardan kurulur:

- Linux: `apt`, `dnf`, `pacman` veya `zypper`
- macOS: Homebrew
- Windows: `winget` ve Windows OpenSSH Client

Linux ve Windows hazırlık aşamasında yönetici parolası veya UAC onayı
isteyebilir. macOS'ta Homebrew yoksa önce [brew.sh](https://brew.sh/) üzerinden
kurulmalıdır.

`websocket-client` bağımlılığı dağıtım paketinde bulunur ve çevrim dışı kurulur.

## İndirme dosyaları

Kullandığınız işletim sistemine ait paketi indirin:

- Linux: `EX520v-root-linux.tar.gz`
- macOS: `EX520v-root-macos.tar.gz`
- Windows: `EX520v-root-windows.zip`

Her paketin yanında bütünlük kontrolü için aynı adlı `.sha256` dosyası bulunur.
Proje herhangi bir uzak sunucuya otomatik olarak dosya veya kimlik bilgisi
göndermez.

## Kurulum

Kurulum sırasında modemin açık kalmasını ve bilgisayarın modem ağıyla
bağlantısının kesilmemesini sağlayın. Mümkünse bilgisayarı modeme doğrudan
Ethernet kablosuyla bağlayın.

### Windows

1. `EX520v-root-windows.zip` dosyasını normal bir klasöre çıkartın.
2. `ex520-root.bat` dosyasına çift tıklayın.
3. UAC penceresi açılırsa gerekli izni verin.
4. Araç modem panelini açtığında yönetici bilgilerinizle giriş yapın.
5. Terminalde `TAMAMLANDI` mesajı görünene kadar pencereyi kapatmayın.

Arşivin SHA-256 değerini PowerShell ile kontrol etmek için:

```powershell
Get-FileHash .\EX520v-root-windows.zip -Algorithm SHA256
```

### Linux

```sh
sha256sum -c EX520v-root-linux.tar.gz.sha256
tar -xzf EX520v-root-linux.tar.gz
cd EX520v-root
chmod +x ex520-root
./ex520-root
```

### macOS

```sh
shasum -a 256 EX520v-root-macos.tar.gz
tar -xzf EX520v-root-macos.tar.gz
cd EX520v-root
./ex520-root.command
```

macOS uygulamayı engellerse Finder'da `ex520-root.command` dosyasına sağ
tıklayıp **Aç** seçeneğini kullanın.

## Panel girişi ve kurulum akışı

Araç stok `admin/admin` bilgilerini yalnızca bir kez dener. Bu bilgiler geçerli
değilse açılan modem paneline mevcut kullanıcı adınız ve parolanızla giriş
yapın. Başarılı giriş algılandığında işlem otomatik devam eder. Panel parolası
kaydedilmez.

Kurulum sırasında araç:

1. Modeli ve firmware sürümünü doğrular.
2. Cihaza uygun tam veya çekirdek root profilini seçer.
3. Özgün Lifemote durumunu kaldırma işlemi için yedekler.
4. Dosyaları yerel TCP/18084 aktarım sunucusundan modeme gönderir.
5. Kalıcılık kancasını ve root servislerini kurar.
6. SSH, Telnet, API, güvenlik duvarı ve profile ait web özelliklerini doğrular.
7. Bağlantı bilgilerini terminalde gösterir.

Bilgiler her modem için ayrı olarak aşağıdaki dizinde tutulur:

```text
~/.local/state/ex520-root/devices/<cihaz-kimliği>/
```

## Komutlar

Linux örneği:

```sh
./ex520-root --dry-run
./ex520-root --status
./ex520-root --panel
./ex520-root --uninstall
```

Windows örneği:

```powershell
.\ex520-root.bat --dry-run
.\ex520-root.bat --status
.\ex520-root.bat --panel
.\ex520-root.bat --uninstall
```

| Komut | Açıklama |
| --- | --- |
| `--dry-run` | Modemde değişiklik yapmadan bağlantı, model ve firmware kontrollerini çalıştırır |
| `--status` | Portları ve kurulu root bileşenlerini denetler |
| `--panel` | Araç tarafından yönetilen modem panelini açar |
| `--uninstall` | Doğrulanmış Lifemote yedeğini geri yükler ve root bileşenlerini kaldırır |

Modem farklı bir IP adresindeyse çalıştırmadan önce `EX520_HOST` değişkenini
ayarlayın:

```sh
EX520_HOST=192.168.1.1 ./ex520-root
```

```powershell
$env:EX520_HOST = "192.168.1.1"
.\ex520-root.bat
```

## Sorun giderme

### `YENİDEN TETİK` mesajı tekrarlanıyor

`[YENİDEN TETİK]` mesajı, modemin kurulum dosyalarından birini bilgisayardan
alamadığını ve aracın aktarımı tekrar denediğini gösterir. Windows'ta mesaj
tekrarlanıyor ve aktarım ilerlemiyorsa:

1. Aracı kapatın.
2. **Windows Güvenliği > Güvenlik duvarı ve ağ koruması** bölümünü açın.
3. Etkin ağ profilini seçin ve **Microsoft Defender Güvenlik Duvarı** seçeneğini
   geçici olarak kapatın.
4. `ex520-root.bat` dosyasını yeniden çalıştırın.
5. Kurulum tamamlanır tamamlanmaz Windows Güvenlik Duvarı'nı yeniden açın.

Bu işlem sırasında yalnızca güvendiğiniz modem ağına bağlı kalın. Araç normalde
modem IP'si için TCP/18084 üzerinde geçici bir izin oluşturur ve işlem sonunda
bu izni otomatik kaldırır; bazı Windows yapılandırmalarında genel güvenlik duvarı
ilk aktarımı yine de engelleyebilir.

### Modem paneli açılmıyor

- Bilgisayarın modem ağına bağlı olduğunu doğrulayın.
- Tarayıcıdan `http://192.168.1.1/` adresini açmayı deneyin.
- VPN, proxy veya farklı ağ bağlantılarını geçici olarak kapatın.
- Modem farklı bir adres kullanıyorsa `EX520_HOST` değişkenini ayarlayın.

### Kurulum yarıda kaldı

Aracı yeniden çalıştırın. Araç mevcut kurulumu denetler, sağlıklı bileşenleri
korur ve eksik dosyaları tamamlamaya çalışır. Aynı IP adresini kullanan farklı
modemler LAN kimliğine göre ayrılır.

### SSH anahtarı değişti uyarısı

SSH sunucu anahtarı her modem için ayrı `known_hosts` dosyasında tutulur. Modem
fabrika ayarlarına döndürüldüyse veya aynı cihaz kimliğiyle farklı bir modem
kullanılıyorsa ilgili cihaz durumunu doğrulamadan eski anahtar kaydını silmeyin.

## Güvenlik

- Root parolası, API tokenı ve SSH anahtarı ilk kurulumda rastgele üretilir.
- SSH yalnızca araca ait özel anahtarla kimlik doğrular; parola girişi kapalıdır.
- SSH sunucu anahtarı ilk bağlantıda cihazın özel `known_hosts` dosyasına
  kaydedilir; sonraki anahtar değişiklikleri sessizce kabul edilmez.
- Root servisleri yerel ağ arayüzüyle sınırlandırılır ve WAN erişimi engellenir.
- Stok panel parolası okunmaz veya kaydedilmez.
- Yerel kimlik bilgileri kullanıcıya özel dosya izinleriyle saklanır.
- Kaldırma işlemi özgün Lifemote yedeğini doğrulamadan modem durumunu değiştirmez.

## Lisans

Projenin özgün kaynak kodu GNU General Public License v3.0 veya sonraki bir
sürüm altında lisanslanmıştır (`GPL-3.0-or-later`). Ayrıntılar için
[LICENSE](LICENSE) dosyasına bakın. Paketle dağıtılan üçüncü taraf bileşenler
kendi lisanslarını korur; ayrıntılar [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES)
dosyasındadır.

Copyright (C) 2026 Emir Yücel
