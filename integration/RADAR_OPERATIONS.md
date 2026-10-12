# Radar ortak kuyruk ve çalışma denetimi

12 Ekim 2026 değişikliği mevcut iş, araştırma ve fikir kayıtlarını değiştirmez.
Eski 89 temel kayda ek olarak güncelleme öncesindeki 91 katalog/geçmiş kaydı
`state/v2/protection/checkpoints/shared-queue.json` ile alan bazında korunur.

## İş dağıtımı

Beş mevcut görev aynı ortak kuyruğu işler. Eski `lane` değişmez; yeni protokolde
sahiplik, işin sırası ve çalışma kimliğiyle oluşturulan tek yazımlık claim'dir.
Eski claim'ler 90 dakikalık sürelerini korur. Yeni claim'ler 30 dakikalıktır;
süresi dolunca controller 5/30 dakika beklemeyle en fazla üç deneme açar.
Yeni deneme, geç kalan eski sonucun kabulünü engeller. Aktif kilit çalınmaz.

Sıra, mümkün olduğunda iki güncel iş / bir birikmiş iş biçimindedir. Her grupta
birleştirme, doğrulama ve haber taraması dönüşümlü ilerler. Beşinci görev boş
birleştirme kuyruğunu beklemek yerine araştırmaya katılır. Tercih edilen çalışan
yalnızca çakışmayı azaltır; başka çalışan aynı işi güvenle devralabilir.

Mevcut beş görev Türkiye saatiyle 07:05–23:05 arasında saat başına bir kez,
aynı dakikada başlar. Daha sık veya ek gizli görev kurulmaz. Güncel ayarlar
`state/v2/config.json` ile kaydedilmiş görev takvimlerinde aynı olmalıdır.

## Müdahale nasıl görünür?

Başlangıç kaydı uzun araştırmadan önce yazılır. Claim ve sonuç sonrası, uzun
araştırmada en geç 15 dakikada bir ilerleme kaydı yazılır. Sonuç ancak geçerli
claim + receipt gerçekten depoya kaydedildiğinde sayılır; görev tetiklenme saati
başarı sayılmaz. Her çalıştırma finished veya blocked olayıyla kapanır.

| Sinyal | Eşik / davranış |
|---|---|
| Görev hiç başlamadı | Beklenen başlangıçtan 15 dakika sonra alarm |
| Başladı, ilerleme kaydı kesildi | Son kayıttan 20 dakika sonra alarm |
| Kuyrukta kalıcı sonuç yok | Etkin çalışma saatinde 45 dakika sonra alarm |
| Sonuçsuz bitti / erişim engeli | İlk controller kontrolünde alarm |
| Controller güncel değil | Sağlık kaydı 40 dakikadan eskiyse görev raporunda uyarı |

`state/v2/health.json` gerçek gözlemleri ve yapılacak işlemi taşır. GitHub Actions
sağlık adımı alarmda hata ve iş özeti üretir. Görev yanıtı gerektiğinde
**MÜDAHALE GEREKLİ** ile başlar; görülen hata ve istenen işlem açıkça yazılır.
Bağlantı/onay gerektiği yalnızca gözlenen hata bunu söylüyorsa belirtilir.
Kuyruk diğer çalışanlarla ilerler; hiçbir izin veya sağlayıcı sınırı atlanmaz.

Bu eşikler kontrol mantığıdır, tam zamanında bildirim garantisi değildir.
GitHub/ChatGPT zamanlayıcı gecikmeleri olabilir. GitHub bildirimleri ve görev
yanıtı teslimi kullanıcının mevcut bildirim ayarlarına bağlıdır. Yeni e-posta,
mesajlaşma veya ücretli izleme servisi eklenmez. Controller tümüyle durursa kendi
hatasını bildiremez; mevcut beş görev sağlık kaydının yaşını ayrıca kontrol eder.

## İki saatlik hedef

Günlük hedef ilk çalışma saati 07:05'ten iki saat sonra 09:05'tir. Geç oluşturulan
günlük giriş için pencere oluşturulma zamanında başlar. Devreye alma denemesinde
`operations.startup_probe.requested_at` ayrı iki saatlik pencereyi başlatır.
İlk uygun controller çalışması `state/v2/windows/*.json` içine değişmez bir
durum raporu yazar. Rapor gerçek gözlem saati ve zamanlayıcı gecikmesini içerir.

Doğrulanmış fikirler hazır oldukça yayımlanır. İki saat dolunca bitmemiş iş
silinmez, tamamlandı sayılmaz ve araştırma ölçütleri gevşetilmez. Tarama,
birleştirme ve doğrulama kapasitesi ayrı ölçülür. En az 15 dakikalık gözlem ve
aşama başına üç kalıcı sonuç olmadan hızdan süre çıkarılmaz. Sonraki aşamaların
iş miktarı bilinmiyorsa bütün işin bitiş tahmini `null` kalır.

## Canlı kabul ve geri dönüş

Yerel testler ayrı geçici verilerle çalışır; gerçek worker başarı kaydı üretmez.
Canlı kabul, her beş çalışanın başlangıç + claim + geçerli sonuç kaydıyla ölçülür.
`all_five_receipt_verified` ancak bu beş kanıt gerçekten varsa true olur.

Değişiklik öncesi kod: `backup/pre-shared-queue-20261012`.
Sorunda önce mevcut beş görevi duraklatın ve config mode=maintenance yapın.
Gerekirse yalnızca kod/prompt/workflow değişikliklerini ileri yönlü bir commit
ile geri alın; önceki config'in tamamını veya veri dizinlerini eski hale çekmeyin.
Katalog/geçmiş, eski ve yeni job/claim/receipt/event/window dosyalarını ve
yayınları aynen koruyun. Yeni protokol kayıtları varken eski engine'i active
modunda başlatmayın. Görev ayarlarının önceki hali özel geri dönüş arşivindedir.
Eski veritabanı senkronizasyonu ve eski araştırma görevleri kapalı kalmalıdır.
