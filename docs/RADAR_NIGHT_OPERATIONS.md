# AIStartup Radar — gece işletimi ve güvenli manuel müdahale

## Üretim başlangıç koşulu
- İlk 91 fikir ve tarihsel araştırma korunur. Değişiklik öncesi dal:
  backup/pre-night-operations-20261012.
- Main bakım modunda kaldıkça ChatGPT görevleri durdurulmuş olmalıdır.
- PR #6 kabul testleri geçip incelenmeden ve ayrı üretim etkinleştirmesi
  yapılmadan ilk araştırma çalışması başlatılmaz.
- Otomatik başlama penceresi Europe/Istanbul 00:01 dahil, 07:00 hariçtir.
  **07:00'den sonra yeni claim oluşturma yasağı kaldırıldı.** Saat 07:00,
  çalışan bir Worker'ın claim veya sonuç kaydetmesini kesmez. Kullanıcı
  dört araştırma Worker'ından istediğini 7/24 manuel başlatabilir.
  Sınırsız kullanım plan varsayımıdır; gerçek sağlayıcı limitleri geçerlidir.

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
- GitHub Actions alarmı, ne doğrulanmış sonuç ne de heartbeat ilerlemesi 30 dakika görülürse olay açar; yeni bir olayda bir kez failure verir.
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
3. Günün HER SAATİNDE istenen Worker için ayrı sohbet komutu ver:
   "Radar WORKER_ID=1 (veya 2/3/4) için MANUEL ÇALIŞTIRMA:
   main config.mode=active ise kuyruktaki sıradaki uygun işleri
   WORK_PROTOCOL'e göre arka arkaya işle, gerçek UUID ile started,
   first-writer claim, sonuç, read-back ve heartbeat kayıtlarını
   oluştur; katalog, jobs ve görev/saat ayarlarını değiştirme."
   Manuel işlem yalnızca bu açık kullanıcı talimatıyla başlatılır;
   zamanlanmış görevlerin sonraki gece başlaması beklenmez.
   Bir iş tamamlandıktan sonra kapasite yetiyorsa sıradakine geç.
   Saatin 07:00 sonrası olması yeni claim açmayı ENGELLEMEZ.
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

## Kanıt tamamlama ve Worker throughput güncellemesi — 13.10.2026
- Original validation receipt outcome=done + decision=unverified is kept immutable.
  The candidate is NOT qualified and the old review is NOT reusable as approval.
- The deterministic controller creates a linked validation job with
  payload.evidence_followup including round, parent_job_id, parent_receipt_path,
  prior_reason and the missing_checks. At most two extra rounds; no infinite loop.
- Only checked, dated, genuinely read and supported existing evidence can shorten
  repeat research. Old research notes and inaccessible URLs are not proof.
- Before claim creation validate job/input_hash, inbox entry/attempt, actual
  worker 1..4 start event, paths, token and 30-minute lease using the checklist
  in radar/claim_guard.py and WORK_PROTOCOL. Fail closed without writing when
  there is an identity mismatch.
- On GitHub 409/422 read back then skip if owned. On 401/403 stop and report
  without bypass. On transient 429/5xx/timeout first read back, then retry
  at most three times. Do not invent technical error categories.
- Manual throughput target is at least 20 evidence-investigated small work units
  WHEN feasible; it never overrides primary-source, date-scoped direct-
  competitor, feasibility, history or immutable write rules. Final report
  separates durable review receipts, new qualified catalog records, unverified
  decisions and open evidence followups. The system can report an unmet target.
- GitHub status.json includes evidence_research.followup_jobs/open/
  terminal_unverified/max_rounds; older validated ideas and baseline 91 remain
  under unchanged protection checks.
