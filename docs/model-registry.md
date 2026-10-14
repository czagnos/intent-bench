# Model kataloğu / Model catalog

Sol menüde **Model kataloğu** sayfası bulunur. LLM ve embedding bağlantıları bu ekrandan eklenir, düzenlenir, test edilir veya devre dışı bırakılır. Kayıtlar çalışma alanına ait SQLite veritabanında tutulur; yeniden başlatmada korunur. Başlangıç modelleri ve mevcut `.env` varsayılanları kullanılmaya devam eder.

## OpenRouter

1. **OpenRouter’dan keşfet** bölümünde LLM veya Embedding seçip model/üretici adına göre arayın. Liste sabit preset dosyasından değil, OpenRouter'ın güncel model API'lerinden gelir. Beş dakika önbelleğe alınır; **Listeyi yenile** tekrar getirir.
2. **Kataloğa ekle** ile model adını ve bağlantı ayarlarını inceleyip kaydedin. Mevcut `INTENT_OPENROUTER_API_KEY` kullanılır. Her tür için ortak anahtar boşsa, o türün mevcut resmi OpenRouter bağlantısındaki servis anahtarı kullanılabilir; özel sunucu anahtarları taşınmaz.
3. Listeye erişilemezse veya başka bir varyant denenecekse **Model kimliğiyle ekle** ile tam OpenRouter model kimliğini girin. Kaydetmek modelin hesabınızda çalıştığını doğrulamaz; **Bağlantıyı test et** ile kontrol edin.
4. **Gelişmiş model ayarları** bölümünden JSON modu, reasoning, çıktı token bütçesi, temperature gönderimi, timeout ve sağlayıcı kısıtı değiştirilebilir. Keşif ekranı JSON/temperature/reasoning seçeneklerini sağlayıcının bildirdiği destekten başlatır. Modelin sağlayıcıları farklı yeteneklere sahip olabilir; bağlantı testi bu hesabın gerçek çağrısını kontrol eder.

Cloud modelleri de eklenebilir. **Model kartı bulunanlar** filtresi OpenRouter'ın Hugging Face kimliği bildirdiği kayıtları gösterir; indirme, lisans ve donanım uygunluğu doğrulaması değildir. Model kartı olmayan kayıtlar da listede kullanılabilir.

## TypeSafe Jev

**TypeSafe Jev ekle** düğmesi `jev-1.13.0`, `https://api.typesafe.ai/v1` ve `INTENT_TYPESAFE_API_KEY` ile doğrudan bir TypeSafe bağlantısı açar. Sunucunun `.env` dosyasına anahtarı ekleyin, formu kaydedin ve **Bağlantıyı test et** düğmesini kullanın. Anahtar sonradan eklendiyse **Bağlantıları yenile** kullanılabilirliği günceller. Kayıt, OpenRouter keşfi veya anahtarına ihtiyaç duymaz; mevcut embedding bağlantınızla **Canlı demo** ve **Deneyler** ekranlarında seçilebilir.

TypeSafe yalnız LLM seçim aşamasında kullanılır. TypeSafe API'si `POST /systemone` ile yapılandırılmış seçim döndürür; OpenAI JSON/reasoning/temperature/çıktı tokenı ayarları bu bağlantıda gösterilmez. Model kimliğini ve timeout değerini düzenleyebilirsiniz. Özel anahtar adı gerekiyorsa `INTENT_MODEL_KEY_` ile başlayan bir değişken de kullanılabilir. [Kurulum, API farkı, fiyat kaynağı ve kontrollü karşılaştırma adımları](typesafe-jev.md).

## Gerçek on-prem veya özel endpoint

**On-prem model ekle** ile:

| Alan | Örnek / anlam |
|---|---|
| Görünen ad | `Bank Qwen GPU-1` — aynı modelin farklı sunucularını ayırır |
| Model türü | `LLM` veya `Embedding` |
| Model kimliği | Sunucunun kabul ettiği served-model adı; OpenRouter slug'ı olmak zorunda değil |
| API kök adresi | `http://localhost:8001/v1` veya bankanın erişilebilir HTTPS API adresi |
| Kimlik doğrulama | Anahtarsız veya sunucudaki özel anahtar değişkeni |
| Embedding profili | `auto`, `qwen3`, `e5`, `plain`; özel served-model adında profili açıkça seçin |

Adres, IntentBench **API sürecinden** erişilebilir olmalıdır; tarayıcıdan erişim yeterli değildir. `/chat/completions` ve `/embeddings` son eklerini uygulama ekler. OpenAI uyumlu JSON HTTP arayüzü beklenir. Model ağırlıkları bu ekranla indirilmez veya bir GPU sunucusu başlatılmaz.

Anahtar gerekiyorsa sunucunun `.env` dosyasına örneğin:

```dotenv
INTENT_MODEL_KEY_BANK_LLM=your_private_server_key
```

Arayüzde **Anahtar değişkeninin adı** alanına yalnızca `INTENT_MODEL_KEY_BANK_LLM` yazın. Özel değişkenler `INTENT_MODEL_KEY_` ile başlamalıdır. Anahtarı sonradan eklediyseniz **Bağlantıları yenile** ile ekranlardaki kullanılabilirlik durumunu güncelleyin. Anahtarın değeri tarayıcıya, veritabanına veya deney çıktısına yazılmaz. Uygulama `.env` dosyasını değiştirmez. OS ortamı dosyadan önceliklidir; dosyadaki bu özel değişkenler her yeni işlemde tekrar okunur. Docker `env_file` veya process environment ile verilen değer değişirse süreci/container'ı yeniden başlatın. Ayrı bir anahtar dosyası için `INTENT_MODEL_CREDENTIALS_FILE=/absolute/path/model.env` kullanılabilir.

On-prem kayıtlara OpenRouter anahtarı gönderilmez. Anahtarsız seçenekte Authorization başlığı yoktur. Genel OpenAI uyumu için thinking parametresi varsayılan olarak gönderilmez; sunucunuz destekliyorsa `chat_template` veya `top_level` ayarı seçilebilir.

## Deney, kalibrasyon ve sonuçlar

- Aynı modeli farklı endpoint veya ayarlarla iki kez kaydedip karşılaştırabilirsiniz. Bağlantı kimliği, yapılandırma sürümü ve görünen ad sonuçlara eklenir; anahtarlar eklenmez. Kayıt güncellemesi kuyruğa alınmış bir deneyin ayarlarını değiştirmez.
- Her embedding bağlantısı/ayar kümesi kendi indeksini ve kalibrasyon kimliğini kullanır. Endpoint, model veya embedding ayarları değişince kalibrasyonu yeniden hesaplayın. Yalnızca görünen adı veya anahtarın değerini değiştirmek aynı modelin kalibrasyonunu bozmaz; anahtar değişimi eski HTTP istemcisini yeniden kullanmaz.
- Devre dışı bırakılan kayıt yeni isteklerde seçilemez; eski deneyler korunur. Tek deneyde katalog büyüklükleri dahil mevcut **32 kombinasyon** sınırı geçerlidir; kayıt sayısı çalışma alanı başına en fazla 200'dür.
- `prompt` JSON modu API'ye `response_format` göndermez; şemayı prompt'a koyar. Yanıt yine Pydantic şeması ve aday intent üyeliği ile doğrulanır. Hatalı çıktı yönlendirilmez.

```bash
.venv/bin/python scripts/check_models.py --list-models --workspace demo
.venv/bin/python scripts/check_models.py --llm-only --llm-id model_REPLACE_WITH_ID
```

## Katalog vektörlerini saklama ve reindex

Embedding indeksleri `INTENT_DATA_DIR/vector-indexes/` altında kalıcıdır (varsayılan: `data/private/vector-indexes/`). Docker'da `/app/data/private` için mevcut `studio-data` volume'u kullanılır. API yeniden başladığında aynı katalog/model/temsilin dosyasını yükler; API anahtarının değişmesi uyumlu disk vektörlerini geçersiz kılmaz. Yeni kullanıcı mesajı için sorgu embedding'i yine hesaplanır.

İlk API başlangıcı demo kataloğunu oluşturur. İlk semantik istekten önce, uygulamayla aynı veri dizinini ve `.env` dosyasını kullanan terminalde:

```bash
.venv/bin/python scripts/warm_models.py --workspace demo --embedding-id model_REPLACE_WITH_ID
```

Hazır indeks diskten yüklenir; eksikse tüm katalog hesaplanıp kaydedilir. Komut örnek sorgu veya LLM çağrısı yapmaz. Intent ekleme/çıkarma, tanım/örnek veya embedding ayarları değişince tam reindex çalıştırın:

```bash
.venv/bin/python scripts/reindex.py --workspace demo --embedding-id model_REPLACE_WITH_ID
```

`.env` varsayılanı için `--embedding-id default` kullanın. Her iki komutta `--catalog-version VERSION` mevcut bir sürümü sabitler; belirtilmezse başlangıçtaki aktif sürüm kullanılır. `--representation combined` veya `--representation separate` ilgili temsilin dosyasını hazırlar; aksi halde sunucu ayarı geçerlidir. Yeni çalışma alanı/katalog üretmezler; eksik seçim hata verir.

Başarılı JSON çıktısındaki `source=disk` mevcut dosyanın kullanıldığını, `built` ilk hazırlığı ve `rebuilt` tam reindex'i gösterir. `generation`, boyut, metin sayısı, model, katalog sürümü, süre ve dosya yolu da yazılır. Reindex eski dosyayı yalnız tam hesaplama bittiğinde atomik değiştirir; hata olursa önceki dosya korunur. Çalışan API sonraki istekte yeni nesli yükler, devam eden deneyler başladıkları nesli korur. Bozuk dosya reindex uyarısı verir; otomatik yeniden hesaplanmaz. Docker komutu: `docker compose exec studio python scripts/reindex.py --workspace demo --embedding-id default`. [Başlangıç ve saklama ayrıntıları](../README.md#connect-models-deliberately).

Bu PoC'nin model yönetimi, mevcut yerel yönetici erişimi kapsamındadır. Workspace ayrımı kayıtları ayırır; kullanıcı kimlik doğrulaması veya kurum yetkilendirmesi eklemez.

## Güncelleme

Discovery 503 hatasında uygulama logundaki `OpenRouter discovery failed` satırını inceleyin. `category` alanı timeout, bağlantı, sıkıştırma, JSON/katalog formatı veya sağlayıcı hatasını; `upstream_status` varsa OpenRouter'dan alınan gerçek HTTP kodunu gösterir. API yanıtında aynı bilgiler `diagnostics` altında yer alır. Anahtarlar ve ham sağlayıcı yanıtları loglanmaz.

9 Eylül düzeltmesi: sıkıştırılmış model listesi HTTP istemcisi tarafından açıldıktan sonra ikinci kez açılmaya çalışılıyordu. Bu, başarılı gzip yanıtını da 503'e dönüştürüyordu. Yeniden oluşturulan yanıtın sıkıştırma/uzunluk başlıkları düzeltildi. LLM ve embedding için gzip/deflate, sağlayıcı hata kodları ve güvenli tanı bilgileri dahil 57 ilgili backend testi ve production build geçti.

Çalışan API'yi durdurup repo kökünde:

```bash
.venv/bin/pip install -r requirements.lock
npm --prefix apps/web ci
npm --prefix apps/web run build
PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002
```

Mevcut `.env` dosyasını koruyun. Arayüzü API sunuyorsa güncel production build gerekir. Yeni SQLite tablosu otomatik oluşturulur; intent kataloğu ve vaka etiketleri değiştirilmez.

## English quick guide

Open **Model catalog** in the sidebar. Use **Discover on OpenRouter** to search the current LLM or embedding list, inspect a model card, and **Add to catalog**. **Add by model ID** also accepts manual OpenRouter IDs. **Add on-prem model** registers any reachable OpenAI-compatible model server using its served model name and API base URL.

**Add TypeSafe Jev** creates a direct TypeSafe connection with pinned `jev-1.13.0`. Set `INTENT_TYPESAFE_API_KEY` in the server `.env`, save and test the connection, then select it in **Live demo** or **Experiments**. It uses TypeSafe's native decision API with the existing embedding/retrieval pipeline. OpenRouter discovery and OpenAI-specific generation settings are not used. See the [TypeSafe guide](typesafe-jev.md).



OpenRouter uses the existing server key. For authenticated OpenAI-compatible private endpoints, put `INTENT_MODEL_KEY_BANK_LLM=your_key` in the server `.env` and enter only the variable name in the form. Custom key variables are reread from that file without restarting; process environment variables take precedence and require restarting the process when changed. Keys are never returned by the registry API or stored in experiment exports.

After adding an environment-based key, use **Refresh connections** to update model availability. Enabled connections with configured keys and supported response contracts can be selected in the live demo and experiment matrix; embeddings also appear in calibration. Use **Test connection** for a small probe that may incur API usage. Success confirms connectivity and the response contract, not accuracy. Separate registrations let you compare the same model on different endpoints. Recalibrate after changing an embedding connection or inference settings. Model card availability alone does not establish on-prem licensing or hardware suitability.

## API sources

OpenRouter discovery uses [`/api/v1/models`](https://openrouter.ai/api/v1/models) for text-output LLMs and [`/api/v1/embeddings/models`](https://openrouter.ai/docs/api/api-reference/embeddings/list-all-embeddings-models) for embeddings, with no pagination arguments to request the full list. The UI filters and paginates the returned metadata. Model-card links use the optional [`hugging_face_id` field](https://openrouter.ai/docs/client-sdks/python/components/model). Discovery makes no inference requests.
