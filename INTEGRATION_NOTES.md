# Entegrasyon notu

Bu dizin `emrycl/EX520v-tek-tus-root-araci` projesinden alınmıştır.

Ana projedeki iki SSH yoklaması, sistem genelindeki host key kontrolünü devre
dışı bırakan `StrictHostKeyChecking=no` / `UserKnownHostsFile=os.devnull`
seçeneklerini kullanıyordu. EX520v OpenWrt Tool entegrasyonunda bunlar cihaz
bazındaki `SSH_KNOWN_HOSTS_FILE` ile `StrictHostKeyChecking=accept-new` olarak
değiştirildi. Böylece ilk bağlantı cihazın özel durum dizinine kaydedilir ve
sonraki anahtar değişiklikleri sessizce kabul edilmez.

Root yöntemi, firmware imza kontrolleri, kimlik bilgisi üretimi ve diğer
işlevler değiştirilmedi. Değişiklik GPL-3.0-or-later altında dağıtılır.
