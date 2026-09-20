# EX520v Tek Tuş Root Aracı

EX520v modemlerde stok panel, SSH ve Telnet üzerinden kalıcı root erişimi
sağlayan kurulum aracıdır.

## Uyarı

Bu proje yalnızca sahibi olduğunuz veya yönetmek için açık izin aldığınız
cihazlarda bilgilendirme, araştırma ve modem firmware'inde bulunan özellikleri
kullanabilme amacıyla hazırlanmıştır. Yetkisiz erişim, hizmet engelleme, ağlara
izinsiz müdahale veya başka yasa dışı işlemler için kullanılmamalıdır. Aracı
kullanan kişi cihaz, ağ ve yürürlükteki mevzuat bakımından tüm sorumluluğu kabul
eder.

Firmware üzerinde değişiklik yapmak cihazın garanti veya destek koşullarını
etkileyebilir. Başlamadan önce modem ayarlarınızı yedekleyin.

## Desteklenen cihaz

- Model: `EX520v`
- Donanım: tüm EX520v revizyonları
- Firmware: `EX520v_260514`

Araç kuruluma başlamadan önce model ve firmware sürümünü doğrular. Uyuşmazlık
varsa modeme dosya göndermez.

## İndirme

Dağıtım dosyaları bu klasörde yer alır. Proje herhangi bir uzak depoya
otomatik dosya göndermez.

### Linux — test edildi

- `EX520v-root-linux.tar.gz`
- `EX520v-root-linux.tar.gz.sha256`

### macOS — test edilmedi

- `EX520v-root-macos.tar.gz`
- `EX520v-root-macos.tar.gz.sha256`

### Windows — test edilmedi

- `EX520v-root-windows.zip`
- `EX520v-root-windows.zip.sha256`

Araç fiziksel modem üzerinde yalnız Linux ortamında denenmiştir. macOS ve
Windows başlatıcıları hazırlanmış ve statik olarak kontrol edilmiş, ancak bu
platformlarda gerçek cihaz kurulumu yapılmamıştır.

## Gereksinimler

- Modem paneline yerel ağ erişimi

Başlatıcı eksik Python, Chrome/Chromium, OpenSSH ve Linux firewall
araçlarını denetler. Desteklenen sistemlerde eksikleri şu kaynaklarla kurar:

- Linux: `apt`, `dnf`, `pacman` veya `zypper` ve `sudo`;
- macOS: Homebrew;
- Windows: `winget` ve Windows OpenSSH Capability.

Linux ve Windows kurulum sırasında yönetici parolası/onayı isteyebilir. macOS'ta
Homebrew sistemde yoksa güvenlik nedeniyle uzaktan bir betik otomatik
çalıştırılmaz; Homebrew bir kez `https://brew.sh` adresinden kurulmalıdır.

Python `websocket-client` bağımlılığı paket içinde bulunur ve internet
bağlantısı gerektirmeden kurulur. Eksik sistem uygulamalarının ilk kurulumu
ise işletim sisteminin paket kaynağına erişim gerektirir.

Güvenlik duvarı modemden gelen kurulumu engelliyorsa araç aktarım için geçici
bir izin ekler. Linux'ta izin modem IP'si ve TCP/18084 ile sınırlıdır; macOS'ta
paketteki Python yorumlayıcısına geçici uygulama izni verilir; Windows'ta
TCP/18084 yalnızca modem IP'sine açılır. Sistem yönetici parolası veya UAC
onayı isteyebilir. İzin işlem bitince otomatik kaldırılır; parola kaydedilmez.

## Bağlantı

Modemi Ethernet kablosuyla doğrudan bilgisayara veya aynı yerel ağdaki bir
cihaza bağlayabilirsiniz. `http://192.168.1.1/` adresinin açılması yeterlidir.
Farklı bir panel adresi kullanılıyorsa `EX520_HOST` değişkeniyle belirtilebilir.

Aynı paket birden fazla modemde kullanılabilir. Araç aynı IP adresini kullanan
cihazları LAN kimliğinden ayırır; parola, SSH anahtarı, API tokenı ve kaldırma
yedeğini her modem için ayrı yönetir.

## Kurulum

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

Finder engellerse `ex520-root.command` dosyasına sağ tıklayıp **Aç** seçeneğini
kullanın.

### Windows

ZIP dosyasını çıkartın ve `ex520-root.bat` dosyasına çift tıklayın. SHA-256
değerini PowerShell ile kontrol edebilirsiniz:

```powershell
Get-FileHash .\EX520v-root-windows.zip -Algorithm SHA256
```

## Panel girişi

Araç stok `admin/admin` bilgilerini yalnızca bir kez dener. Bilgiler geçerli
değilse açılan stok modem paneline kendi kullanıcı adınız ve şifrenizle giriş
yapın. Başarılı giriş algılandığında kurulum kendiliğinden devam eder. Stok
panel parolası kaydedilmez.

Kurulum sonunda terminalde şunlar gösterilir:

- stok panel için `root` hesabı ve parolası;
- UID 0 SSH komutu ve özel anahtar yolu;
- UID 0 Telnet bilgileri;
- Port Mirror, Paket Yakalama ve CWMP stok sayfa adresleri.

Araç ancak UID 0 Telnet/SSH, root API, kalıcılık, gerçek panel Root
backend'i, Port Mirror, Paket Yakalama, CWMP ve Sistem Araçları altındaki 16
stok sayfanın tamamı doğrulandığında kurulumu başarılı sayar. Firmware etiketi
aynı olsa bile gerekli binary imzaları uyuşmazsa başarılı sonucu vermez.

## Diğer komutlar

```sh
./ex520-root --status
./ex520-root --panel
./ex520-root --uninstall
```

Farklı modem adresi:

```sh
EX520_HOST=192.168.1.1 ./ex520-root
```

## Güvenlik

- Root parolası, API tokenı ve SSH anahtarı ilk kurulumda rastgele üretilir.
- Bilgiler dağıtım paketinde bulunmaz.
- SSH yalnız kurulumda üretilen anahtarı kabul eder.
- SSH sunucu anahtarı her modem için ayrı `known_hosts` dosyasında tutulur;
  fabrika sıfırlanan başka bir cihaz aynı IP'yi kullansa bile sistem geneli
  `~/.ssh/known_hosts` kaydıyla çakışmaz.
- Root servisleri yerel ağ firewall kurallarıyla sınırlandırılır.
- Her modem için ayrı kimlik bilgileri tutulur.
- Kaldırma işlemi özgün Lifemote durumunu doğrulamadan değişiklik yapmaz.

Yerel kimlik bilgileri `~/.local/state/ex520-root` altında `0600` izinleriyle
saklanır.

## Açılan erişimler

- stok panelde gerçek root hesabı ve backend erişimi;
- TCP/2222 üzerinde anahtar tabanlı UID 0 SSH;
- TCP/2323 üzerinde parolalı UID 0 Telnet;
- token korumalı yerel root API;
- stok Port Mirror, Paket Yakalama ve CWMP sayfaları;
- yeniden başlatma sonrasında kalıcı kurulum.

Araç yeni bir modem web sayfası oluşturmaz; firmware içindeki stok sayfaları ve
stok backend nesnelerini kullanır.

## Lisans

Bu projenin özgün kaynak kodu GNU General Public License v3.0 veya sonraki bir
sürüm altında lisanslanmıştır (`GPL-3.0-or-later`). Ayrıntılar için
[LICENSE](LICENSE) dosyasına bakın. Paketle birlikte dağıtılan üçüncü taraf
bileşenler kendi lisanslarını korur; ayrıntılar
[THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES) dosyasındadır.

Copyright (C) 2026 Emir Yücel
