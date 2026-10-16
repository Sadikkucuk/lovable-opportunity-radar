# Radar v3 · CP22 · 15 Ekim 2026 fikir kartları ve genişletmeler

- Katalog: 91 eski fikir aynen korunur; 7 ayrı MVP adayı ve iki birleşik MVP (toplam 9) fikir kartı olarak eklenir.
- Geliştirme kararı **kullanıcıda**. Yeni kartların tamamı `development_selection_status=not_selected` ve `verification_status=user_selected_pending_validation` durumundadır; bunlar QA'dan geçmiş ürün veya geliştirmeye alınmış proje değildir.
- Rakip sayısı kısıtı kaldırılmıştır; bilinmeyen rakip sayıları **null**, uydurulmuş sıfır değildir.
- Beş genişletme `state/manual-v3/2026-10-16-cp22-products-and-extensions.json` içinde kendi mevcut ürün kayıtlarına bağlıdır; eski 91 fikir koruması yüzünden kart içerikleri değiştirilmez. Web okuyucusunda genişletmelerin görünmesi için ayrıca `existing_product_extensions` kaynağının desteklenmesi gerekir.
- Manuel Lovable senkronizasyonunda önce `docs/radar/current.json` ve referans verdiği immutable release dosyasını al; `content_sha256` doğrula; 100 fikir ve eski 91 UUID/key korumasını denetle.
- Beş genişletme **yeni ürün değildir**, katalog sayısını artırmaz. Mevcut worker'lara, cron'a, jobs/claims/results'e müdahale edilmedi.
- Kaynak, varsayım, sınır ve müşteri doğrulama işlerini kartlarda açıkça gör; mevcut CP22 araştırma detayları Kitaplık checkpoint'inde saklanır.
