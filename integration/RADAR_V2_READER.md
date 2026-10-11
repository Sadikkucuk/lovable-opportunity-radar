# Lovable katalog okuyucu sözleşmesi

Proje: 210185f2-dd13-428c-8c51-9457080eb720.
Bu değişiklik yalnız fikir okuma/senkron yolunu değiştirir. Tasarım, hesaplar,
proje talepleri, ödeme veya diğer uygulama verileri kapsam dışıdır.

- GitHub `docs/radar/current.json` → content-addressed `path` release dosyası.
- `content_sha256` alanı release dosyasının UTF-8 ham baytlarının SHA-256 özetidir.
  Sayıların Python/JavaScript JSON yazım farkından etkilenmemesi için önce dosyanın
  ham metnini bu özetle karşılaştır, ardından JSON parse et. release_id dosya adıdır.
- Beklenen schema_version=2; idea_count ile dizi boyutu ve unique UUID/key kontrolü.
- legacy_count=89 olmalı; bütün eski canonical_key'ler gelen tam pakette bulunmalı.
- Başarılı tam paket atomik değiştirilir; kısmi/bozuk/erişilemeyen pakette son sağlam
  kopya kullanılır. İlk ziyaret için 89 eski satırın birebir gömülü kopyası bulunur.
- Eski UUID, her alan, sıralama, açıklama ve detay URL'leri korunur. Veri tablosuna
  INSERT/UPDATE/DELETE/DDL çalıştırılmaz. Yeni kayıtlar GitHub'dan okunur.
- Bilinmeyen sayı/maliyet null kalır; verification_status birebir korunur.
  500 kredi kontrolü veya unknown→qualified varsayımı yoktur.
- Eski visit/cron/admin senkronu veritabanına yazmaz; sadece statik okuma önbelleğini
  yeniler. Admin fikir görünümü de aynı katalog okuyucusunu kullanır.
- Mevcut admin soft-delete davranışı varsa ayrı mevcut moderasyon katmanında
  korunur; GitHub yayını silme/geri getirme işlemi yapamaz.
- Fikir kataloğunu okumak dış DB'ye bağlı olmaz. Mevcut hesap/proje talepleri
  altyapısı ayrı kalır; Radar geçişi bunları silme yetkisi değildir.

Eski 89 satır sitenin kendi mevcut verisinden bir başlangıç kopyasına alınır;
GitHub public deposuna veritabanı dışa aktarımı yazılmaz. Korunan eski kayıt
anahtarları sitedeki kopyayla eşleştirilir ve eski UUID/alanlar aynen döndürülür.
Yeni kayıtların UUID'leri statik katalogdan gelir.
