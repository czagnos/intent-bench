# Bankacılık intent yönlendirmesi için embedding seçimi

Karar tarihi: 8 Eylül 2026. İlk cloud PoC adayı **Qwen3-Embedding-4B**. Amaç 800 intent arasından LLM'e doğru adayları getirmek; değerlendirme ölçütleri öncelikle Recall@5/10/20, ardından uçtan uca intent doğruluğu, OOS davranışı ve sıcak sorgu p95 gecikmesi olmalıdır.

Bu seçim müşteri verisinde ölçülmüş bir birincilik değildir. Türkçe bankacılıkta kesin tercih, bağımsız ve insan tarafından doğrulanmış vaka etiketleriyle yapılacak karşılaştırmadan çıkacaktır.

## Neden 4B?

- Açık ağırlık ve Apache-2.0 lisansı on-prem kullanımına uygundur.
- Qwen3 ailesi 100'den fazla dili ve göreve özel sorgu talimatlarını destekler. Bankacılık niyetlerini getirmesini söyleyen İngilizce bir görev talimatı kullanıyoruz; müşteri sorgusu Türkçe kalır.
- Aynı model ailesinin yayımlanmış çok dilli MTEB değerlendirmesinde 4B, 0.6B'nin üzerinde ve 8B'ye yakın sonuç verir. Bunlar Türkçe bankacılık accuracy yüzdeleri değildir.
- OpenRouter'ın aktif model kataloğunda 4B doğrulandı. LLM ve embedding tek hesap/anahtarla denenebilir. GPU sunucusu kurmadan ilk müşteri deneyi yapılabilir.

Kaynaklar: [Qwen3-Embedding-4B model kartı ve değerlendirmesi](https://huggingface.co/Qwen/Qwen3-Embedding-4B), [OpenRouter model sayfası](https://openrouter.ai/qwen/qwen3-embedding-4b), [OpenRouter embeddings API](https://openrouter.ai/docs/api_reference/embeddings).

## Karşılaştırma sırası

| Model | Deneydeki rolü | Uygulama notu |
|---|---|---|
| Qwen3-Embedding-4B | İlk doğruluk odaklı aday | OpenRouter: qwen/qwen3-embedding-4b; yerel: Qwen/Qwen3-Embedding-4B |
| Qwen3-Embedding-8B | Daha büyük modelden ek kazanım var mı? | OpenRouter: qwen/qwen3-embedding-8b; aynı qwen3 giriş profili |
| Qwen3-Embedding-0.6B | Daha küçük modelle hız/kalite dengesi | Yerel veya uygun sağlayıcı; OpenRouter aktif katalog kontrolünde görünmedi, oradaki sayfası tek başına erişim kanıtı değil |
| multilingual-e5-base | Önceki ölçümlerle referans | Mevcut yerel model; e5 profili |
| BGE-M3 | Başka bir çok dilli mimariyle kontrol | Yerel BAAI/bge-m3, plain profili; bu uygulama dense vektörü kullanır |

BGE-M3'ün sparse ve çoklu vektör desteği bu adaptörde etkin değildir; mevcut sözcüksel bileşen BM25/karakter TF-IDF'dir. [BGE-M3 model kartı](https://huggingface.co/BAAI/bge-m3).

Güncel bir ek aday [Microsoft Harrier-oss-v1-0.6b](https://huggingface.co/microsoft/harrier-oss-v1-0.6b): MIT lisanslı, 94 dil ve güçlü yayımlanmış çok dilli sonuçlar sunuyor. Kendi sorgu prompt sözleşmesi uygulanmadan Qwen/E5 profiliyle çalıştırılmamalı. Bu teslimde Harrier entegrasyonu veya ölçümü yapılmadı.

## Hız ve doğruluk nasıl okunmalı?

800 kısa intent kaydının vektör karşılaştırması ile sorgu embedding çıkarımı ayrı maliyetlerdir. Katalog vektörleri süreçte bir kez hazırlanıp bellekte tutulur; her yeni sorguda sorgu embedding'i çıkarılır. Katalogda intent başına birden çok örnek bulunduğundan indeks 800'den fazla vektör içerir. İlk indeks oluşturma süresini sıcak sorgu gecikmesine karıştırmayın. HTTP ağı, servis kuyruğu ve donanım gerçek ölçüme dahildir; 4B için henüz p95 taahhüdü yoktur.

Önceki 26 kapsam içi demo vakasında E5 Recall@20 zaten %100'dü; karar doğruluğu 23/26 ve üç kapsam dışı sorunun tamamı yanlış kabul edilmişti. Dolayısıyla embedding değişimi tek başına seçilen doğruluk hedefinin sağlandığını göstermez. Aday doğru olduğu halde seçim hatalıysa Qwen/policy; aday hiç gelmiyorsa katalog/embedding incelenmelidir. Bu demo sonuçları müşteri benchmark'ı değildir.

Model/profil değiştirildiğinde API yeniden başlatılır ve indeks yeniden oluşturulur. Aynı katalog, aynı veri bölünmesi, aynı K, aynı Qwen modeli ve aynı karar kurallarıyla ayrı deneyler karşılaştırılır. Mevcut arayüz tek aktif embedding modeli kullanır; modeller arasında `.env` üzerinden geçilip ayrı deney kayıtları alınır. Eski sonuçlar kendi embedding model/profil bilgisini korur.

## Bu teslimde doğrulanan sınır

Model kimlikleri ve API dokümantasyonu kontrol edildi; giriş biçimleri, anahtar çözümleme, hata yanıtları, batch sırası ve yönlendirme entegrasyonu taklit HTTP yanıtlarıyla test edildi. API anahtarı kullanıcı tarafından local ortamda ekleneceği için canlı OpenRouter çağrısı, Qwen embedding accuracy'si ve cloud gecikmesi henüz ölçülmedi.
