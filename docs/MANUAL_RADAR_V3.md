# Radar v3 — Kullanıcının Başlattığı Manuel Çalışma

## Amaç ve sınırlar
- Araştırma, bir kullanıcı isteğiyle tek sohbet oturumunda gerçekleştirilir. Günlük 40 haber / 5 aday gibi yapay bir üst sınır yoktur.
- Toplanan tüm haberler envantere girer; her gerçek doğrulama sonucu kendi kaynaklarıyla kaydedilir. Eksik inceleme kesinlikle "tamamlandı" değildir.
- Eski 91 kayıt, kaynak kimlikleri, canonical_key ve URL'ler korunur. Eski v2 işleri silinmez veya tamamlanmış gibi yeniden işaretlenmez.
- Mevcut v2 worker otomasyonları, kullanıcı ayrı olarak onay verene kadar korunur. Geçiş bitene kadar v2 kontrolör ve GitHub yayıncı ile çakışan yazma yapılmaz.
- Harici ücretli araştırma API'si, LLM, veritabanı, secret veya yeni servis zorunlu tutulmaz.
- Yeni ürünün çalışması ücretli/ücretsiz harici API, veritabanı veya AI servisinin varlığına bağlı olamaz.
- Her izin gerektiren GitHub yazma işlemi normal kullanıcı onayı ve sağlayıcı yetkileriyle gerçekleştirilir. Güvenlik reddi olursa durulur, alternatif çağrılarla aşılmaya çalışılmaz.

## Günlük iş akışı
1. GitHub main SHA, v2 config/status, docs/batches/index.json, state/idea_catalog.json, state/idea_history.json, docs/radar/current.json ve site senkronizasyon yanıtlarını oku.
2. Son 72 saatin tüm kaynak/URL envanterini oluştur; v2'de işlenmiş kimlikleri ayır, güncel haberleri öne al, geçmiş borcu koru. Kaynakların başarılı çekilmesi haberlerin incelendiği anlamına gelmez.
3. Her haber için kararı kaydet: no_opportunity / opportunity / duplicate / unverified. Gerçek orijinal URL, tarih, yayınevi, erişilen metin ve delil düzeyini belirt.
4. Olası her ürün için değişim/delta, aktör, müşteri, JTBD, mevcut sürtünme, giriş/iş akışı/çıktı, ticari değer ve Lovable uygulanabilirliğini açıkla.
5. Aynı olaydan türeyen haberleri ve hedef müşteri + temel iş + ürün mekanizması eşleşen fırsatları birleştir.
6. Doğrudan Türkiye rakiplerini (kanıtlanan 0) ve global rakipleri (en fazla 3) tarihlenmiş canlı aramalarla değerlendir; komşu çözümleri ayrı kaydet. Bulunamayan rakip = otomatik 0 değildir.
7. Çalışma zamanı için dış API, dış veritabanı, dış AI bağımlılığının yokluğunu doğrula. Kaynaklar erişilemezse aday HOLD/unverified kalır.
8. History ile semantik tekilleştirme, kaliteli kanıt zinciri, tam ürün kartı ve orijinal kaynak denetimi tamamlanmadan yayınlanamaz.
9. Çalışmanın kanıtlarını ve kararlarını atomik, tarihli checkpoint olarak bir feature branch altında sakla. Her checkpoint: examined_count, verified_count, hold_count, qualified_count, unprocessed_count, source_index_hash, main_base_sha ve kanıt URL'leri.
10. Yayın kararı açıkça doğrulanmışsa v2 mevcut acceptance koşullarıyla uyumlu valid receipt + controller yayını veya ayrıca test edilen v3 publisher PR kullan; mevcut v2 jobs/claims/results üzerinde sentetik değişiklik yapma.
11. Commit ve read-back sonrası site sunucusunun gerçek release_id/total yanıtını doğrula. Site senkronizasyonu ve gerçek ziyaretçi gösterimi ayrı sonuçlardır.
12. Gün sonunda tüm açık/kapalı iş, yeni gelenler, ürün sayısı, yayın SHA'sı ve doğrulanmamış kaynakları raporla.

## Güvenlik ve kapasite
- İzin veya güvenlik reddi olduğunda dur, tam ret metnini bildir; claim/lease kimlik kontrollerini değiştirmek, sahte zaman damgası üretmek veya sahte onay yazmak yasaktır.
- Araştırma tek bir cevaba sığmazsa checkpoint'e kadar gerçek sonuçları kaydet; kullanıcı yeni oturumda "Radar'a devam et" dediğinde o checkpoint'ten devam edilir.
- "Tüm kuyruğu bitir" hedefi gerçek araştırma sınırlarına tabidir; eksik kanıtla toplu nitelikli karar üretilmez.
- Çalışmaya başlamadan önce v2 ve v3 yazma yollarının çakışmadığı doğrulanmalı. Kullanıcı onayı olmadan v2 automations kapatılmaz.

## İlk günün gerçek başlangıç metrikleri — 2026-10-14
- Main kontrolü: 617 ready (412 Discovery işi, 205 Validation işi), 291 done, 7 unverified.
- Katalog/release: 91 fikir; eski 89 korunuyor.
- V2 controller errors: 3; open evidence followup: 8.
- Site sync son gözlem: 91 toplam (89 eski + 2 yeni).
- Bu belge araştırma receipt'i veya yayın commit'i yerine geçmez.


## OTURUM BAŞINA ZORUNLU KAPASİTE — MİNİMUM 20 ADAY (2026-10-14 KULLANICI KARARI)
Bu başlık manuel Radar v3 için diğer kapasite ve raporlama ifadelerinden üstündür; günlük 40 haber / 5 aday limiti geçersizdir.

1. Kullanıcı "devam et", "işe koyul" veya benzeri açık manuel çalışma emri verdiğinde, normal oturum hedefi **en az 20 ayrı fırsat adayının uçtan uca araştırma ve nihai kararının tamamlanması, kanıta bağlanması ve mümkünse GitHub'a checkpoint commit'inin atılmasıdır**. İşlem ve yanıt sayısını yapay olarak sınırlama. 20 bir taban hedeftir, tavan değildir; elverişli ise daha fazla devam et.
2. "Aday tamamlandı" saymak için karar **qualified / rejected / semantic_duplicate** olmalı ve ilgili gerçek kaynaklar, geçmiş karşılaştırması, işlevsel gerekçe ve gerekli pazar/teknoloji kanıtları kaydedilmiş olmalı. Opened, read, triaged, candidate_seen, prechecked, pending, hold ve unverified sonuçları tamamlanan 20'ye DAHİL DEĞİLDİR.
3. Qualified kararı ancak orijinal tetikleyici haber doğrulanmış, müşterinin gerçek işi ve iş akışı tanımlanmış, Türkiye doğrudan rakip araması tarihli/kaynaklı (tespit edilen 0), global doğrudan rakip araması tarihli/kaynaklı (en çok 3), ücretsiz ve dış servis bağımsız MVP doğrulanmış, history semantik çakışma denetimi geçmiş ve eksiksiz ürün kaydı üretilmişse verilebilir. Belirsiz rakip sayısı sıfır değildir. Sadece bir manşet veya RSS özeti yetmez.
4. Rejected kararı somut gerekçe ve gerçek kontrol kanıtını gerektirir: doğrulanmış ürün politikasına aykırılık, belgeli uygulanamazlık veya yeterli doğrulamadan sonra makul gerekçeyle elenen fırsat. Eksik erişim veya araştırmaya vakit yetmemesi otomatik rejected değildir; HOLD'dur.
5. Semantic_duplicate kararı için önceki ürünün canonical_key, adı, müşteri, JTBD ve ürün mekanizması alanlarıyla somut eşleştirme bulunmalı; yüzeysel isim benzerliği veya tahmini match tek başına yeterli değildir. Çakışma kararına karşı örnek varsa HOLD olarak yeniden değerlendirilir.
6. **Akış:** başta 20+ adaylık parti seç → kaynak ve geçmiş indeksini oku → birbirinden bağımsız gerçek kontrolleri paralel yürüt → her sonuç için kanıt ve karar kaydet → GitHub read-back doğrulaması → 20 terminal karara ulaşana kadar mümkün olduğunca sonraki adaylarla sürdür → gerekiyorsa yayın ve site son kontrolü.
7. Tek bir araştırma paketi kullanıcı isteği olmadan **1–2 adayda kesilmez**. Ara sonuçta kullanıcıya durum verilebilir; ancak mümkün olduğu ölçüde araç çalışmasına devam edilir. Oturum boyunca yavaşlık veya çoklu araç çağrıları, yüzeysel/fabrikasyon delille hızı artırma gerekçesi olamaz.
8. Gerçek sağlayıcı/izin/güvenlik engeli, bağlantı kesilmesi veya oturum kapasitesi nedeniyle 20'ye ulaşılamazsa, kaydedilen **gerçek terminal karar sayısı**, hold ve examined sayıları ayrı raporlanır; **20 tamamlandı** denmez. Kaydedilebilir kısmı geri okunabilir checkpoint'e yaz, sonraki oturumu kalan adaylardan başlat.
9. Yeni kayıtlar mevcut v2 iş/claim/result dosyalarının üzerine yazılmaz. v3 kontrol yoluna GitHub feature branch üzerinden açıkça kanıtlı checkpoint olarak aktarılır. V2 controller veya prod siteye eşitleme ayrı kalite/yayın kapılarından geçer.
10. Etkin 5 zamanlanmış eski worker veya çalışma saatleri kullanıcı ayrıca istemedikçe değiştirilmez. Tam geçişte kullanıcı onayı, katalog korunumu ve test edilmiş yeni publisher gerekir.
11. Her cevap bitmeden mümkünse **En az 20 terminal aday**, **bekleyen/HOLD**, **GitHub commit ve okunarak doğrulanan kayıt**, **yeni katalog fikri**, **site release_id / gösterim**, **engeller** rakamlarıyla ayrıştırılır.

### Manuel kullanma komutu
“Radar'a devam et. Canlı GitHub kuyruğundan ve bir önceki v3 checkpoint'inden başlayarak EN AZ 20 ADAYI kaynaklarıyla uçtan uca analiz edip terminal karara bağla; 20'den sonra kapasite varsa devam et. Tamamlanan kararları GitHub'a kaydet ve read-back doğrula. QUALIFIED olanları, bütün kalite/koruma/yayın şartları geçildiğinde siteye ulaştır. Hold ve inceleme ayrı sayılsın. Engeli doğrudan bildir; güvenlik/izin kontrollerini atlatma.”
