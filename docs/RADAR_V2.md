# Radar v2 — işletim ve geri dönüş

10 Ekim 2026. Kalıcı kuyruk GitHub JSON, araştırma mevcut beş ChatGPT görevi,
denetim/yayın standart GitHub Actions ve Python standart kütüphanesindedir.
Model API'si, yeni veritabanı, dış agent, sunucu veya secret eklenmez.

## Değişmeyen kayıtlar

89 katalog ve 89 geçmiş kaydının bütün alanları `state/v2/protection/baseline.json`
ile korunur. Yayıncı eski kaydı güncelleyemez/silemez. Tarihsel şema uyumsuzlukları
eski kayıtlara dokunularak düzeltilmez; yeni kayıtlar sıkı kontrolden geçer.
Sitedeki 89 kayıt ve UUID'leri özel geri dönüş arşivinde ve sitenin kendi başlangıç kopyasında aynen korunur; eski
etiketler yeniden doğrulanmış sayılmaz. V2 yalnız yeni fikirleri ekleyebilir.

## İş sözleşmesi

`jobs/` değişmez giriş; `claims/<job>/<attempt>.json` ilk yazanın sahiplenmesi;
`results/<job>/<attempt>.json` değişmez sonuç. `prompts/WORK_PROTOCOL.txt` tek
işlem sözleşmesidir. Kontrolcü bütün worker'larla aynı sonuçları okur. A/B ve
chunk dosyaları yalnız tarihsel arşivdir. İş kuralları `radar/engine.py` içinde
uygulanır; yeni şema eski 89 kaydı yeniden yazma izni vermez.

90 dakikalık sahiplenme süresi, en fazla 3 deneme; geçici hata için 5/30 dakika
bekleme. Üçüncü başarısız denemeden sonra failed; bu doğrulama değildir.
Yeni sahiplenme eski denemenin geç yazısını geçersiz kılar. Her iş bağımsızdır.
Haber taraması 10 kayıtlık, doğrulama bir adaylık kayıt birimleridir. Aynı ChatGPT
çalıştırması bu birimlerden kapasitesi elverdiğince arka arkaya işler.

Günlük girdi İstanbul tarihine göre commit SHA ve tam haber kopyasıyla sabitlenir.
Tekrarlı URL'ler tekilleştirilir; başlık değişikliği yeni kimlik üretmez. İçerik
özeti değişince haber tekrar incelenir. Aynı içerik/politika için tarama 30 gün,
doğrulanamayan haber/aday 1 gün, aday kararı 7 gün kullanılabilir. Kanıtın yayın
anında yedi günden eski olması yalnız o adayın yayınını tutar.
10 Ekim'den gelen 95 aday, aynı içerikleri ve eski araştırma yollarıyla taşındı.
Eski haber paketinin geçmişte doğru sabitlendiği geriye dönük iddia edilmez.

Kaynaklara gerçek erişim, arama ve bilimsel/ticari yorum ChatGPT'nin görevidir;
Python, bir modelin yazdığı gözlemin dünyadaki doğruluğunu tek başına kanıtlamaz.
Python eksik kaynak, yanlış kimlik, belirsiz sayıyı sıfır yapma, yasak bağımlılık,
yanlış sayaç ve kayıt çakışması gibi yapısal sorunları engeller.

## Takvim

Kontrolcü her saatin 02/17/32/47. dakikasında ve yeni sonuç geldiğinde toparlar.
Beş mevcut ChatGPT görevi desteklenen saatlik aralıklarla farklı dakikalarda
çalışır. Görev kotaları ve platform izinleri sürer; Actions ChatGPT çalışmasını
istediği anda başlatmaz. Gece yarısında açık işler korunur. Tetikleme gecikirse
sonraki çalışma eksikleri yeniden bulur. Public depoda standart runner kullanılır.

`state/v2/status.json` ve run raporları aynı kayıtların hesaplanmış görünümüdür.
İşleme durumu, kanıt kararları ve yayın ayrı alanlardır. İncelenmeyen haberler
kapsama sayılmaz. Eksikle kapanan iş `complete_with_gaps` olur. Yetki kaldırılırsa
kullanıcı tarafından yeniden bağlantı gerekebilir; hiçbir izin denetimi atlanmaz.

## Yayın

Tek Actions yayıncısı katalog/geçmiş/release/pointer değişikliklerini aynı Git
commit'inde kaydeder. main değişirse eski sonucu rebase etmez; yeni HEAD'den
yeniden hesaplar. Yeni kayıt için kaynak, tarihli rakip araştırması, dış API/DB/AI
olmayan mimari ve semantik yenilik gerekir. Rakip eşiği TR=0/global<=3 korunur.
Lovable kredisi, domain ve hosting için değerlendirme üst sınırı yoktur.
Yanlış veritabanı senkronizasyonu kaldırılmıştır. Statik yayın adresi
`docs/radar/current.json`; içerik SHA adındaki değişmez release dosyasındadır.
Site eski 89 satırı aynen gösterir; bilinmeyen yeni değerleri sıfıra dönüştürmez.
GitHub yayını site teslimi sayılmaz; site kontrolü ayrıca yapılır.

## Kabul testleri

`python -m unittest discover -s tests -v`

Kayıt değişikliği/silinmesi, sabit girdi, 10 haberlik birimler, URL tekrarları,
worker çökmesi, geç sonuç, yarışan sahiplenme, üç başarısız deneme, tekrar beklemesi,
yanlış girdi, null değerler, bağımlılık yasağı, aday izolasyonu, mükerrer yayın,
89 kayıt koruması, gece yarısı, bozuk sonuç, önbellek ve bakım modu sınanır.

## Geri dönüş

Yedek dal: `backup/pre-radar-v2-20261010-0933`.
Kaynak commit: `345e7c18647624639f4861d43f5599431f4f4d6e`.
Lovable başlangıç commit: `ae3096454f77cee7467d697658c4a44bae2e75eb`.
Görevlerin önceki tanımları ve site satırları özel `Radar_Geri_Donus_20261010.zip`
arşivinde bulunur. Orchestrator yedek alındığında zaten kapalıydı.

1. Beş ChatGPT görevini durdur; config.mode=maintenance yap ve commit et.
2. Güncel HEAD ve yeni fikirleri ayrı bir yedek dalla sabitle.
3. `python -m radar.rollback` geri alınacak kod yollarını gösterir.
4. `python -m radar.rollback --apply` yalnız çalışma ağacını hazırlar. Yeni veriler,
   eski 89 fikir ve kanıt dosyaları korunur. İncele, normal ileri commit oluştur.
   Force push/reset ile main'i geçmişe götürme. Eski DB senkronu kapalı kalır.
5. Lovable kodunu başlangıç commit'inden ileri sürümle geri getir; DB satırlarını
   silme/yeniden yükleme. Görevleri arşivdeki ID/prompt/schedule/enabled değerlerine
   geri getir. Bilinen eski sistem sorunları geri döneceği için eski üretimi ancak
   kaynağı/yayın akışını kontrol ederek etkinleştir.
6. `python -m radar.engine check` ile bütün korunan alanları tekrar karşılaştır.

Rollback önce kodu değiştirir; yeni toplanmış fikir ve kanıtları silmez.
