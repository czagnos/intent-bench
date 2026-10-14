# TypeSafe Jev ile intent seçimi

Jev, intent adayları arasında seçim yapan doğrudan bir TypeSafe bağlantısı olarak eklenir. Embedding modeli ve arama stratejisi mevcut akışta çalışmaya devam eder. Canlı demo ve deneylerde Jev'i diğer LLM bağlantılarıyla aynı veri üzerinde karşılaştırabilirsiniz.

TypeSafe, eğitim yaklaşımını **RLCD — Reinforcement Learning for Calibrated Decisions** olarak tanımlıyor: amaç serbest metin üretmek yerine karar ve olasılık döndürmek. Bu, sağlayıcının teknik açıklamasıdır; Türkçe bankacılık verimizde kalibrasyon, hız veya doğruluk ölçümü değildir. [TypeSafe AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer).

## Kurulum

1. Repo kökündeki sunucu `.env` dosyasına anahtarınızı ekleyin:

   ```dotenv
   INTENT_TYPESAFE_API_KEY=your_typesafe_key
   ```

2. **Model kataloğu → TypeSafe Jev ekle** seçin. Hazır formda bağlantı **TypeSafe**, model türü **LLM**, model `jev-1.13.0`, API kökü `https://api.typesafe.ai/v1` ve anahtar değişkeni `INTENT_TYPESAFE_API_KEY` bulunur. Anahtarın kendisini forma yazmayın.
3. **Modeli kaydet** ve **Bağlantıyı test et** düğmelerini kullanın. Test sabit demo metniyle API erişimini ve karar sözleşmesini kontrol eder; API kullanımına neden olur. Anahtarı kayıt sonrasında eklerseniz **Bağlantıları yenile** seçin.
4. **Canlı demo → Hibrit arama + LLM → Karar modeli (LLM)** alanında Jev'i seçin. Seçilen embedding bağlantısı da kullanılabilir olmalıdır.

Anahtar kaydın kendisinde saklanmaz; kayıt yalnız değişken adını tutar. `INTENT_MODEL_KEY_TYPESAFE_TRIAL` gibi özel bir anahtar değişkeni de kullanılabilir. Anahtarlar OpenRouter'dan devralınmaz ve tarayıcıya/deney çıktısına eklenmez. `.env` içindeki değer her yeni model işlemi için okunur; çalışan süreçte OS ortamından verilen değer dosyadan önceliklidir. Docker `env_file` veya process environment değerini değiştirdiyseniz süreci/container'ı yeniden başlatın. Ayrı anahtar dosyası için `INTENT_MODEL_CREDENTIALS_FILE` kullanılabilir.

Kayıt kimliğini model tablosundan alarak aynı sabit demo kontrolünü CLI ile de yapabilirsiniz:

```bash
.venv/bin/python scripts/check_models.py --llm-only --llm-id model_REPLACE_WITH_ID --workspace demo
```

## API ve karar davranışı

TypeSafe'in API sözleşmesi `POST https://api.typesafe.ai/v1/systemone`, Bearer kimlik doğrulaması ve `model`, `state`, `questions` alanlarını kullanır. `Choice` soruları tanımlanan seçeneklerden birini, seçenek olasılıklarını ve confidence değerini döndürür. [API referansı](https://docs.typesafe.ai/api), [Choice](https://docs.typesafe.ai/primitives/choice).

IntentBench tek HTTP çağrısında intent kararını ve gerektiğinde kullanılacak netleştirme adaylarını sorar. Girdi, mevcut mesajı, yakın konuşma bağlamını, aktif intent'i ve retrieval adaylarının tanım/seçim kurallarını içerir. Testin beklenen intent etiketi modele gönderilmez. Yönlendirme, netleştirme, kapsam dışı, temsilci isteği ve aktif akışı sürdürme/iptal kararları mevcut sunucu politikalarına aktarılır.

Jev sohbet yanıtı veya slot toplama metni üretmez. Netleştirme sorusu sunucuda aday adlarından belirli kurallarla hazırlanır; workflow ve slot toplama mevcut politika katmanında kalır. Bozuk yanıt, tanınmayan aday veya geçersiz olasılık verisi teknik hata olur. Confidence için otomatik bir yönlendirme eşiği eklenmez. Bu değer, mevcut embedding OOS kalibrasyonundan ayrıdır.

Bu bağlantıda OpenAI `messages`, `response_format`, `temperature`, reasoning ve çıktı token bütçesi gönderilmez. Arayüz bu ayarları gizler; timeout düzenlenebilir. Otomatik yeniden deneme eklenmez; limit/servis hataları deneyde görünür kalır. Sağlayıcının `input_tokens` ve `output_tokens` kullanımı mevcut `prompt_tokens`, `completion_tokens` ve `total_tokens` alanlarına dönüştürülür. Sonuçlarda TypeSafe sağlayıcısı ve bu adaptörün prompt sürümü yer alır.

## Model sürümü ve fiyat

17 Eylül 2026 tarihinde belgelenen kararlı model **`jev-1.13.0`**; duyurulan ücret **1 milyon input token için $0.042**, output tokenları ücretsiz. Fiyat ve limitler sağlayıcı tarafından değiştirilebilir. Deney formu sürümü sabitler; `jev-latest` gibi alias'lar ileride başka sürüme geçebilir. [TypeSafe model ve fiyat sayfası](https://docs.typesafe.ai/models).

Çağrı maliyetini sağlayıcının döndürdüğü input token kullanımından hesaplayın; birden fazla soru içeren istek için yalnız kullanıcı mesajının uzunluğu yeterli değildir. Bu entegrasyon faturalama veya otomatik fiyat güncelleme özelliği eklemez.

## Kontrollü karşılaştırma

1. **Deneyler** ekranında yalnız **Hibrit arama + LLM** yöntemini açın. Tek embedding modeli, tek retrieval stratejisi, aynı aday bütçesi ve aynı katalog büyüklüğünü koruyun.
2. LLM listesinde Jev ile karşılaştırma modelini birlikte seçin. Aynı veri kaynağı ve vaka sınırını kullanın; böylece seçilen vakalar her iki modele de uygulanır.
3. İlk incelemeyi demo vakalarıyla yapın. Ana doğruluk, gereksiz netleştirme, kapsam dışı yanlış kabul, teknik hata, seçim süresi ve toplam p95 sonuçlarını birlikte okuyun. Aday Recall@K düşükse seçim modelini değiştirmek retrieval kaybını tek başına çözmez.
4. Gerçek kalite değerlendirmesini ayrı, gözden geçirilmiş müşteri test setinde tekrarlayın. Farklı katalog büyüklükleri veya retrieval stratejilerini sonraki deney olarak ekleyin.

Entegrasyon ve UI testleri kontrollü HTTP/API yanıtlarıyla çalışır. Bu testler gerçek Jev hızını, Türkçe doğruluğunu veya maliyet üstünlüğünü ölçmez. Tek başarılı bağlantı kontrolü de benchmark değildir; model, embedding, katalog, aday bütçesi ve ölçülen vaka kümesiyle birlikte canlı deney sonuçlarına bakılmalıdır.

## 800 intent ile embedding kullanmadan iki aşamalı deney

`scripts/evaluate_direct_jev.py`, kaynak deneyin 800-intent snapshot'ını, sıralı ve incelenmiş seed/test vakalarını, kayıtlı `jev-1.13.0` bağlantısını ve seçim prompt sürümünü çağrıdan önce doğrular. Katalog veya vaka fingerprint'i farklıysa çalışmaz; beklenen etiketler yalnız çağrılardan sonra puanlamada kullanılır.

İlk aşama intent kimliklerini alfabetik sırayla 200'erli dört gruba ayırır. Tek istekte dört bağımsız Choice sorulur; her biri 200 intent ve `@none` içerir. Rubric yalnız intent adı ve açıklamasıdır. Her grubun kendi olasılık sırasından beş intent alınır; gruplar arasında olasılık karşılaştırılmaz. Tam eşitliklerde intent kimliği sırası kullanılır, sıfır olasılıklar da sabit bütçeyi doldurabilir. Çıktı sıfır olasılıkla seçilen adayları ve beşinci sıra sınırındaki eşitlikleri ayrıca kaydeder.

İkinci çağrı, bu 20 adayı mevcut TypeSafe Selector'a tam tanım, ilk sabit katalog örneği, dışlamalar ve seçim kuralıyla verir; mevcut seçim prompt'u değiştirilmez. Embedding, sözcüksel arama veya konuşma kuralıyla erken karar verme kullanılmaz. Model kararı sonrasında mevcut sunucu politikası uygulanır. İlk aşama daha dar katalog alanları kullandığından sonuç bu iki aşamalı protokolün başarısı olarak yorumlanmalıdır.

```bash
.venv/bin/python scripts/evaluate_direct_jev.py \
  --source-evaluation /absolute/path/evaluation.json \
  --output artifacts/runs/jev-direct-800-two-stage.json
```

Ön kontrol için `--limit 1` eklenebilir; çıktı alt kümeyi ve kaynak vaka sayısını açıkça belirtir. Çıktı yolu yeni olmalı ve `artifacts/runs` altında bulunmalıdır. Her vaka sonrasında checkpoint yazılır. İki çağrının token kullanımları toplanır, aşama süreleri ayrı tutulur. İkinci çağrı başarısızsa ilk aşamanın bilinen maliyeti ve adayları korunur. İlk teknik hatada çalışma durur; yeniden deneme, otomatik kesme veya fallback yoktur.

`jev-1.13` için state + tüm soruların toplam sınırı 64k token, state + en uzun tek sorunun sınırı 32k tokendır. 800 intentin tüm örnek/dışlama/seçim kurallarını ilk isteğe koyan sözleşme kontrolü `400 / max_tokens_exceeded` döndürdü. Ad ve açıklama biçimi tam deneyden önce bu API sınırına göre sabitlendi (`jev-partition-shortlist-v2-name-description`); daha uzun girdiler hâlâ limit hatası verebilir. [Jev 1.13 sınırları](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md).

## İlk canlı kontrol — 17 Eylül 2026

`jev-1.13.0`, dört sabit sentetik ifadeyle canlı olarak kontrol edildi; müşteri verisi kullanılmadı. 48 çekirdek demo intent'inden sözcüksel aramayla ilk 20 aday alındı, embedding çağrısı yapılmadı. Her model çağrısı aynı istekte üç `Choice` sorusu içerdi. Bu kontrol semantik/hibrit doğruluk benchmark'ı değildir.

| Senaryo | Gözlenen sonuç |
|---|---|
| Açık yönlendirme isteği | Beklendiği gibi `route` → `card.limit.change` |
| Belirsiz kart kapatma isteği | `clarify` beklenirken hatalı biçimde `route` → `card.cancel` |
| Birden fazla amaç | Beklendiği gibi `clarify` / `multiple_intents`; adaylar `card.limit.change` ve `account.balance` |
| Kapsam dışı istek | Beklendiği gibi `out_of_scope` |

Dört yanıtın tamamı teknik sözleşme kontrollerinden geçti. Tekil çağrı süreleri yaklaşık **0,85–1,20 saniye**, sağlayıcının bildirdiği kullanım çağrı başına **12.984–15.521 input** ve **632–647 output token** oldu. Bunlar her senaryo için tek gözlemdir; p95, genel doğruluk veya başka modellere üstünlük göstermez. Kart kapatma belirsizliğindeki ilk hata korunmuştur; prompt bu örneği düzeltmek için ayarlanmamıştır.
