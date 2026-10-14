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
