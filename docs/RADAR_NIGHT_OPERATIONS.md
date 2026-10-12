# AIStartup Radar — gece işletimi ve güvenli manuel müdahale

## Üretim başlangıç koşulu
- İlk 91 fikir ve tarihsel araştırma korunur. Değişiklik öncesi dal:
  backup/pre-night-operations-20261012.
- Main bakım modunda kaldıkça ChatGPT görevleri durdurulmuş olmalıdır.
- Draft PR #5 kabul testleri geçip incelenmeden ve ayrı üretim etkinleştirmesi
  yapılmadan ilk araştırma çalışması başlatılmaz.
- Gece saati Europe/Istanbul 00:01 dahil, 07:00 hariç. Kapasite sınırsız
  varsayımı çalışma bütçesi planlaması içindir; sağlayıcı erişim, kota,
  çalışma süresi ve güvenlik kontrollerini kaldırmaz.

## Mevcut beş görevin görev ayrımı
- Worker 1 saatlik 00:01..06:01 (dakika 01).
- Worker 2 saatlik 00:04..06:04 (dakika 04).
- Worker 3 saatlik 00:07..06:07 (dakika 07).
- Worker 4 saatlik 00:10..06:10 (dakika 10).
- Orchestrator 00:15..06:15 saatlik; 07:15 ayrıca rapor-only.
- Bu saatler yeniden başlatma anlarıdır: bir ChatGPT çağrısı içindeki
  iş sayısı bir ile sınırlanmaz. Tek çağrının yedi saat aralıksız çalışması
  garanti edilmez.

## Veri bütünlüğü
- Aşamalardan hiçbiri mevcut fikirleri silmez/güncellemez; 91 fikir koruma
  checkpoint'i her kabul testinde doğrulanır.
- Kaynak taraması bütün OPML girişlerini sorgular ve her biri için başarılı,
  başarısız veya boş feed durumunu docs/status.json'a yazar.
- MAX_ITEMS=0 ve MAX_PER_SOURCE=0 toplama sırasında keyfî 1000/40 kırpmasını
  kapatır; 72 saatlik zaman penceresi ve sektörel filtreler hâlâ vardır.
- Özgün kaynak doğrulaması, Türkiye/global doğrudan rakip araştırması,
  mimari uygunluk ve semantik özgünlük kuralları gevşetilmez.

## Görünür durum ve alarmlar
- state/v2/status.json: kuyruk, araştırma ve health özeti.
- state/v2/health.json: start, heartbeat, son sonuç, kritik olaylar.
- state/v2/alerts/night-stall.json: tekilleştirilmiş 30 dakika hareketsizlik
  olayı, opened/recovered zamanları.
- docs/radar/reports/YYYY-MM-DD.md: her sabah 07:05 itibarıyla üretimden
  bağımsız gerçek durum görüntüsü. 07:15 Orchestrator bu dosyayı özetler.
- GitHub Actions alarmı yeni bir olay açıldığında bir kez failure verir.
  E-posta için kullanıcı GitHub hesabında Actions e-posta bildirimini
  etkinleştirmelidir; gerçek e-posta teslimi ayrıca sınanmalıdır.
- ChatGPT sabah e-postası için Settings > Notifications > Email; görevin
  e-posta bildirimleri de etkin olmalıdır. Sistem bunu sessizce açamaz.

## Güvenli manuel çalıştırma
1. GitHub'da state/v2/config.json ve state/v2/health.json dosyalarını oku.
   Mode=maintenance ise otomatik görev başlatma.
2. state/v2/inbox/worker-N.json ve next_page sayfalarından bekleyen tek
   bir iş seç. Claim/result yolları tam olarak controller'ın verdiği
   yollar olsun.
3. ChatGPT konuşmasında 'Radar'ın sıradaki uygun işini mevcut protokole
   göre manuel işle ve sonucu GitHub'a kaydet; hiçbir prompt/katalog
   dosyasını değiştirme' talimatını ver.
4. İlk yazanın kazandığı claim, token ve input_hash doğrulanmadan
   araştırma yapılmış gibi bildirme. 30 dakikalık lease dolarsa
   geç kalmış kayıt üretme; controller'ın sonraki attempt'ini bekle.
5. Sonuç dosyasını kaydet ve geri oku. Teknik hata validation rejection
   değildir. Kaynaklar erişilemiyorsa unverified kaydet.
6. Catalog/history/queue/counters/quality gate dosyalarını manuel
   değiştirme. Yayın yalnız controller aracılığıyla olur.

## Üretime alma / rollback
- Tüm testler başarılı ve günlük rapor e-posta teslimi doğrulandıktan
  sonra önce ChatGPT görevlerinin yeni prompt/zamanlamaları denetlenir;
  sonra config.mode=active ve mevcut görevler etkinleştirilir.
- Sorunda görevleri durdur, mode=maintenance yap, iş kayıtlarını silmeden
  backup/pre-night-operations-20261012 dalını karşılaştır. Main'i force
  push ile geri götürme.
