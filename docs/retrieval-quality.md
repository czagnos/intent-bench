# Katalog büyüdüğünde doğruluğu iyileştirme

Bu paket aynı model ve vakalarla aday bulma, hibrit birleştirme, yeniden sıralama ve son karar aşamalarını karşılaştırır. Amaç, model eğitimi yatırımını hangi aşamanın sınırladığını ölçmektir. Model ağırlıkları bu değişiklikte eğitilmedi.

## Mevcut kurulumu güncelleme

10 Eylül güncellemesi: [taksonomi v2, router/workflow ayrımı ve kontrollü reranker deneyi](taxonomy-and-routing.md). Önceki ölçümler aşağıda tarihsel sonuç olarak korunur; yeni etiket sürümüyle doğrudan accuracy farkı hesaplanmamalıdır.

Repo kökünde, uygulamanın kullandığı dalda:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
```

Çalışan API'yi yeniden başlatın. Mevcut `.env` dosyanızı koruyun. İlk üç strateji mevcut embedding ve LLM bağlantılarıyla çalışır; ek model anahtarı veya ML paketi gerektirmez.

## İlk deney: modeli sabit tut, arama stratejisini değiştir

1. **Deneyler** ekranında yalnız **Hibrit arama + LLM** yöntemini seçin. Sözcüksel referans ve semantik yöntemlerini bu ilk turda kapatın.
2. Tek embedding ve tek LLM seçin. Önce başarılı bağlantı testi olan çifti kullanın.
3. **Arama stratejilerini karşılaştır** seçeneğini açıp **İlk üç stratejiyi karşılaştır** düğmesine basın.
4. **Aranacak katalog büyüklükleri** alanına `48, 200, 800` yazın. Demo için en fazla vaka sınırı en az 29 olsun.
5. Oluşan 9 kombinasyonu çalıştırın. Sonuçları JSON olarak indirin; aday izleri ve kullanılan ayarlar bu dosyada bulunur.

| Hazır strateji | Aday kaynağı | Kaynak başına / havuz / LLM adayı | Karşılaştırılan değişiklik |
|---|---|---|---|
| Mevcut hibrit | Semantik + sözcüksel, eşit RRF | 40 / 20 / 20 | Referans |
| Semantik adaylar + LLM | Yalnız semantik | 40 / 20 / 20 | Sözcüksel kaynağın etkisi |
| Semantik ağırlıklı hibrit | Semantik %75, sözcüksel %25 RRF | 40 / 20 / 20 | Birleştirme ağırlığının etkisi |
| Hibrit + reranker + LLM | Eşit RRF, ardından seçili reranker | 60 / 40 / 8 | Geniş havuzu daraltan alternatif akış |
| Ayrı tanım ve örnek vektörleri | Eşit RRF, ayrı indeks metinleri | 40 / 20 / 20 | Katalog metninin temsil biçimi |
| Kontrol: semantik + LLM | Yalnız semantik | 40 / 20 / 8 | Reranker kapalı kontrol |
| Kontrol: semantik + reranker + LLM | Yalnız semantik, ardından reranker | 40 / 20 / 8 | Yalnız yeniden sıralamanın etkisi |

Hazır stratejilerdeki kaynak, temsil, ağırlık ve aday sayıları düzenlenebilir. Şu ilişki korunur: `LLM adayı ≤ havuz ≤ kaynak başına aday`. Kaynak sınırı 100, LLM sınırı 40'tır. Yöntem, model, strateji ve katalog büyüklüğü çarpımı toplamda 32 kombinasyonu aşamaz. Seçilen aynı test vakaları ve etiketler bütün kombinasyonlarda korunur.

`Semantik adaylar + LLM`, mevcut **Semantik arama** yöntemiyle aynı değildir: adayları embedding bulur, son kararı yine LLM verir. Mevcut semantik yöntemin kalibre edilmiş OOS reddetme davranışı değişmez. Canlı demoda hibrit yöntem seçildiğinde **Arama stratejisi** alanından bu seçenekler tek tek kullanılabilir.

## Ayarlar neyi değiştiriyor?

**Kaynak başına aday**, semantik ve sözcüksel sıralamalarda kaç benzersiz intentin dikkate alındığını belirler. Aynı intentin birden fazla örneği, birleştirmede birden fazla oy almaz. **Aday havuzu**, kaynak birleştirme ve mevcut bağlam/yakın intent eklemeleri sonrasında elde edilen listedir. **LLM'e giden aday**, isteğe bağlı reranker sonrasında son seçime verilen listedir.

RRF, kaynakların ham skorlarını toplamak yerine sıra konumlarını birleştirir. Ağırlık ayarı bu katkıyı değiştirir; skor bir güven olasılığı değildir. Semantik kaynak tek başına seçilirse RRF ağırlığı kullanılmaz.

**Tanım + örnek birlikte** her örneği intent adı ve açıklamasıyla indeksler. **Tanım ve örnek ayrı**, her örneği kendi metniyle ve her intentin ad/açıklamasını ayrıca indeksler. Bu sürümde metin temsili ortak retrieval korpusunu değiştirdiğinden sözcüksel kaynağı da etkiler. Yalnız embedding temsilinin etkisini izole etmek için iki stratejide de aday kaynağını **Yalnız semantik** seçin; diğer ayarları aynı tutun. Temsil değişikliğinde ayrı indeks hazırlanır.

Reranker yalnız havuzdaki adayları yeniden sıralar. Doğru intent havuzda yoksa onu geri getiremez. Eski **Hibrit + reranker + LLM** stratejisi hem havuzu hem son aday sayısını değiştirir. Yeni **Reranker açık/kapalı karşılaştır** düğmesi iki semantik kontrol stratejisini eşit kaynak, temsil ve aday bütçeleriyle seçer; yalnız reranker değişir. Düğmeye basınca bu iki stratejinin düzenlenmiş ayarları varsayılan `40 / 20 / 8` değerlerine döner.

## Reranker bağlama

İlk yerel deneme için `BAAI/bge-reranker-v2-m3` seçildi: açık ağırlıklı, çok dilli bir sıralama modelidir. Bu seçim Türkçe banka verisinde başarı garantisi değildir. [Resmî model kartı](https://huggingface.co/BAAI/bge-reranker-v2-m3)

### Aynı makinede yerel model

```bash
.venv/bin/pip install '.[ml]'
```

Mevcut `.env` dosyasına ekleyin:

```dotenv
INTENT_RERANKER_MODE=local
INTENT_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
INTENT_RERANKER_BATCH_SIZE=16
```

API'yi yeniden başlatınca varsayılan reranker seçilebilir. İlk kullanım model dosyalarını indirebilir; CPU/GPU kapasitesi süreyi etkiler. Yerel kullanımda ayrı API anahtarı gerekmez. Ağsız kullanımda model klasörünü `INTENT_RERANKER_MODEL` olarak ayarlayıp `INTENT_RERANKER_LOCAL_FILES_ONLY=true` kullanın. CrossEncoder sorgu-aday çiftini en fazla 512 token ile işler; uzun tanımlar kırpılabilir. Skorlar kalibre güven olasılığı olarak yorumlanmaz.

### Kendi HTTP servisiniz

**Model kataloğu → Reranker ekle** üzerinden modeli, servis adresini, protokolünü ve gerekiyorsa anahtarın ortam değişkeni adını kaydedin. Örneğin anahtar sunucuda `INTENT_MODEL_KEY_RANK=...` ise forma yalnız `INTENT_MODEL_KEY_RANK` yazılır. Anahtar istemciye veya deney sonuçlarına aktarılmaz.

| Protokol | Gönderilen alanlar | Beklenen yanıt |
|---|---|---|
| Cohere / vLLM | `model`, `query`, `documents`, `top_n` | `results[]`: `index`, `relevance_score` |
| Hugging Face TEI | `query`, `texts`, `raw_scores: true` | Liste: `index`, `score` |

Adaptör verdiğiniz temel URL'nin sonuna `/rerank` ekler. TEI için örneğin `http://127.0.0.1:8081` girilir. Özel servisiniz `/v1/rerank` sunuyorsa temel URL `/v1` ile biter. Servis her belge için benzersiz indeks ve sonlu skor döndürmelidir. Uyumsuz yanıt, timeout ve 429 teknik hata olarak kaydedilir; LLM'e sessiz geçiş yapılmaz. [TEI rerank sözleşmesi](https://huggingface.co/docs/text-embeddings-inference/quick_tour#re-rankers)

Bu sürümde reranker bağlantısı OpenRouter üzerinden kurulmaz. Mevcut OpenRouter LLM/embedding anahtarınız reranker servisine otomatik gönderilmez. OpenRouter model keşfi LLM ve embedding için çalışmaya devam eder. Aynı API ailesindeki her modelin standart CrossEncoder veya bu iki HTTP sözleşmesiyle uyumlu olduğu varsayılmaz; bağlantı testiyle doğrulayın.

## Sonuçları nasıl okuyacağız?

**Doğruluk nerede kayboluyor?** bölümündeki kartlar, beklenen kararı `route` olan ve retrieval aşaması tamamlanan vakaları kullanır. Çalışmayan kaynakta oran `—` gösterilir. Kartlarda K ve pay/payda ayrı görünür. Ana tablodaki accuracy ise teknik hata, yanlış ret ve gereksiz netleştirmeleri başarısız saymaya devam eder.

| Alan | Anlamı | Sonraki inceleme |
|---|---|---|
| Semantik kaynak Recall@K | Doğru intent semantik ilk K içinde mi? | Embedding modeli, görev öneki, örnekler, temsil |
| Sözcüksel kaynak Recall@K | Doğru intent sözcüksel ilk K içinde mi? | Terimler, benzer ürün adları, açıklama tekrarları |
| Aday havuzu Recall@K | Doğru intent birleştirme/bağlam sonrasında kaldı mı? | RRF ağırlıkları ve havuz sınırı |
| Son aday listesi Recall@K | Doğru intent LLM'e gerçekten verildi mi? | Reranker ve son aday sınırı |
| Doğru aday varken doğruluk | Doğru intent son listede bulunan vakaların kaçında doğru route üretildi? | LLM kararı, netleştirme, ret ve workflow politikası |

Son kartın paydasında son aday listesi hazırlanmışken oluşan LLM/politika hataları da kalır. Reranker hatasında son liste boş kalır. Bağlamdan doğrudan çözülen slot/iptal gibi kararlar retrieval başarısı olarak sayılmaz; ayrı sayılır. Üst tablodaki tarihsel Recall@K bütün beklenen-route vakalarını kullanırken aşama kartları yalnız tamamlanan retrieval vakalarını kullanır; hata olduğunda bu iki payda farklılaşır.

Vaka satırında **Aday izini göster**, doğru intentin kaynak, birleştirme, havuz ve son listedeki sırasını gösterir. Her başarısız vaka tek gruba atanır: kaynakta bulunamama, birleştirmede elenme, reranker/aday sınırında elenme, yanlış seçim, gereksiz netleştirme, yanlış ret, politika kararı veya teknik hata. Bu gruplar gözlenen ilk başarısız aşamayı tarif eder; tek başına nedensellik veya etiket doğruluğu kanıtı değildir.

Deney JSON'u kullanılan modelleri, stratejiyi, katalog/veri sürümlerini, kaynak/havuz/son aday kimliklerini, son aday skorlarını, kararları ve aşama sürelerini içerir. Reranker p95 yalnız reranking aşamasının istek başına süresidir; yerel ağırlık hazırlığı ayrı kaydedilir. Toplam p95 sorgu işlemini ölçer; indeks/model hazırlığı ile STT/TTS dahil değildir. Başarısız istek süreleri genel gecikme hesabında kalır.

## Katalog denetimi ve seçim kuralları

**Intent kataloğu → Kataloğu denetle** tanım çakışması adaylarını, birebir aynı örnekleri, test/indeks örtüşmelerini ve test edilen intent kapsamını raporlar. Bu deterministik denetim ek embedding veya LLM çağrısı yapmaz. Katalogdaki bütün anlamsal çakışmaları bulduğu iddia edilmez.

Bir bulgudaki intenti açarak ad, açıklama, örnekler, kapsam dışı ifadeler ve **seçim kuralı** düzenlenebilir. Kural hem LLM'e hem reranker belgesine verilir; güncel prompt sürümü `router-tr-v5-array-contract` olur. Örneğin genel transfer sorgusu ile EFT durum sorgusu arasındaki ayrım, bankanın onayladığı taxonomy kararına göre açıkça yazılabilir. API ayrıca geçerli komşu intent kimliklerini güncellemeyi destekler.

Kaydetme yeni katalog sürümü oluşturur; eski deneyler ve kataloglar korunur. Eşzamanlı eski sürüm üzerinden düzenleme 409 ile engellenir. Değişen katalog için yeni indeks hazırlanır ve kalibre semantik yöntemi kullanmadan önce yeni sürümü kalibre etmek gerekir. Mevcut workflow/slot eşlemesi bu editörden değiştirilemez. Test etiketleri otomatik taşınmaz. İnceleme sonucunda etiket değişmesi gerekiyorsa **Vakalar** ekranında ayrıca doğrulanır ve sonraki deney yeni veri sürümüyle çalışır.

İlk sürümün demo denetimi 148 olası kapsam çakışması çifti bulmuştu; v2 ek genel/özel çiftleri de denetler. Bunlar kesin taxonomy hatası değildir. Demo test soruları 800 intentin yalnız 26'sını kapsıyor; 774 intent için test sorusu yok. Dolayısıyla 800 aday arasından arama testi, 800 intentin her biri için doğruluk doğrulaması sayılmaz. Test sorularını katalog örneklerine kopyalayarak başarı oranını yükseltmeyin; ayrı eğitim/geliştirme/test verisi kullanın.

## Taksonomi v2 öncesinde yapılan ölçüm

Repo verisiyle, aynı 26 beklenen-route vakası ve aynı alt-katalog seçme protokolü kullanılarak **sözcüksel retrieval** çalıştırıldı:

| Aranan intent | Recall@1 | Recall@5 | Recall@20 | Recall@40 |
|---|---|---|---|---|
| 48 | 20/26 (%76,9) | 26/26 (%100) | 26/26 (%100) | 26/26 (%100) |
| 200 | 16/26 (%61,5) | 22/26 (%84,6) | 24/26 (%92,3) | 26/26 (%100) |
| 800 | 14/26 (%53,8) | 20/26 (%76,9) | 22/26 (%84,6) | 22/26 (%84,6) |

800 intentte ilk 40 adayda bulunamayan dört demo etiketi: `card.online`, `transfer.status`, `loan.status`, `service.branch`. Transfer ve kredi durumunda daha özel yeni intentler üst sıralara geliyor; denetim bu nedenle tanım/etiket incelemesini de görünür kılıyor. Etiketler bu ölçümde değiştirilmedi. [Ölçüm özeti](retrieval-quality-verification.json)

Bu ortamda gerçek LLM ve reranker bağlantısı hazır değildi; yerel embedding ağırlıkları da ağsız modda yüklenemedi. Bu nedenle embedding/hibrit/reranker için yeni bir gerçek-model doğruluk kazanımı raporlanmıyor. HTTP sözleşmeleri ve arayüz davranışları kontrollü test yanıtlarıyla doğrulandı; otomatik arayüz testleri gerçek tarayıcıda görsel inceleme değildir.

Güncel veri sürümüyle yeni ölçüm için:

```bash
.venv/bin/python scripts/analyze_retrieval.py --mode lexical --catalog-sizes 48 200 800
.venv/bin/python scripts/evaluate.py --source seed --methods hybrid_llm --catalog-sizes 48 200 800 --retrieval-profiles data/retrieval-profiles.json
```

İlk komut model servisi kullanmaz. İkinci komut mevcut model bağlantılarını kullanır ve API tüketimi oluşturur. `analyze_retrieval.py` ayrıca `--mode semantic`, `--mode hybrid`, `--representation separate` seçeneklerini destekler. Ağsız yerel embedding analizi için `--local-files-only` kullanılabilir. Çıktılar Git dışındaki `artifacts/runs` dizinine yazılır.

## Fine-tuning karar noktası

Önce gerçek müşteri vakalarıyla tanım ve etiket sınırlarını doğrulayın. Ardından aynı veri üzerinde ilk üç stratejiyi, temsil değişikliğini ve kontrollü reranker karşılaştırmasını çalıştırın. Kaynak recall düşük kalıyorsa embedding ve ayırt etmesi zor negatif örnekler; doğru aday havuzda bulunup eleniyorsa reranker; doğru aday LLM'de bulunmasına rağmen yanlış seçiliyorsa LLM için eğitim yatırımı değerlendirilebilir. Teknik hatalar için önce bağlantı/çıktı sözleşmesini düzeltin. Eğitim hedefini demo setindeki birkaç soruya göre seçmeyin; doğruluk, OOS yanlış kabul, kapsam içi yanlış ret ve p95'i birlikte izleyin.
