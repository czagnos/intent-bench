# Dinamik model seçimi ve karşılaştırma

Canlı demo ve deneyler [Model kataloğu ekranından eklenen bağlantıları](model-registry.md) ve sunucudaki [başlangıç modellerini](../data/model-presets.json) kullanır. OpenRouter'ın güncel listesi veya kendi on-prem endpoint'inizden LLM/embedding ekleyebilirsiniz. Mevcut `.env` modeli ve sağlayıcı tercihi **varsayılan** seçenek olarak korunur. Arayüzden model seçimi için API'yi yeniden başlatmak gerekmez.

## Güncelleme

Repo kökünde, çalışan API'yi durdurup:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
PYTHONPATH=apps/api .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002
```

Tarayıcıyı yenileyin. Mevcut `.env` dosyasını değiştirmeyin. Vite geliştirme sunucusu kullanıyorsanız kod değişiklikleri orada da görünür; API güncellemesi için yeniden başlatma gerekir.

## İlk karşılaştırma

Semantik arama varsayılan olarak kalibre edilmiş OOS reddini kullanır. Önce **Kalibrasyon** ekranında seçili embedding modelleri için eşik hesaplayın; önceki referansla karşılaştırmak için **Semantik OOS reddetme → Kapalı** seçin. Hibrit yöntemin karar süreci değişmez. [Kalibrasyon ve İngilizce arayüz rehberi](calibration-and-language.md).

1. **Canlı demo:** yöntemi, embedding modelini ve hibrit yöntem için LLM'yi seçin. Seçim değişince yeni konuşma başlar. Sonuç paneli gerçekten kullanılan modelleri gösterir.
2. **Deneyler:** semantik ve/veya hibrit yöntemi işaretleyin. Embedding ve LLM listesinden birden fazla model seçin. Önizleme, tüm kombinasyonları ve toplam karar sayısını gösterir.
3. Örneğin çalışan Qwen3 Embedding 8B + BGE-M3 ile mevcut Qwen3.5 + GPT-OSS 20B seçimi **4 hibrit kombinasyon** oluşturur. Semantik yöntemi de işaretlerseniz **2 semantik kombinasyon** eklenir. Aynı 29 demo vakası için toplam **174 karar** değerlendirilir.
4. Karşılaştırma satırına tıklayarak metrikleri ve hata ayrıntılarını inceleyin. **İki kombinasyonu vaka bazında karşılaştır** alanında iki embedding'i veya aynı embedding üzerindeki iki LLM'yi yan yana görebilirsiniz. **Yalnız farklı kararlar** filtresi ayrışan vakaları gösterir.
5. JSON indirme; tüm kombinasyonları, model ayarlarını, sabit veri/katalog kimliklerini ve vaka kararlarını içerir. Önceki tek model deneyleri açılmaya devam eder.

İlk koşuda embedding'i sabit tutup LLM'leri karşılaştırmak, sonraki koşuda LLM'yi sabit tutup embedding'leri değiştirmek hangi bileşenin sonucu etkilediğini anlamayı kolaylaştırır. PoC bağlantılarını doğruladıktan sonra müşteri etiketleriyle aynı karşılaştırmayı yapın.

## Hazır LLM profilleri

| Profil kimliği | OpenRouter modeli | Yanıt ayarı | Model kartı / lisans |
|---|---|---|---|
| qwen35-35b | qwen/qwen3.5-35b-a3b | Düşünme kapalı, 600 token | [Qwen3.5](https://huggingface.co/Qwen/Qwen3.5-35B-A3B), Apache-2.0 |
| gpt-oss-20b | openai/gpt-oss-20b | Low reasoning, 4096 token | [GPT-OSS 20B](https://huggingface.co/openai/gpt-oss-20b), Apache-2.0 |
| gpt-oss-120b | openai/gpt-oss-120b | Low reasoning, 4096 token | [GPT-OSS 120B](https://huggingface.co/openai/gpt-oss-120b), Apache-2.0 |
| qwen3-30b-instruct | qwen/qwen3-30b-a3b-instruct-2507 | Reasoning parametresi yok, 600 token | [Qwen3 Instruct](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507), Apache-2.0 |
| deepseek-v32 | deepseek/deepseek-v3.2 | Düşünme kapalı, 600 token | [DeepSeek V3.2](https://huggingface.co/deepseek-ai/DeepSeek-V3.2), MIT |
| glm47-flash | z-ai/glm-4.7-flash | Düşünme kapalı, 600 token | [GLM 4.7 Flash](https://huggingface.co/zai-org/GLM-4.7-Flash), MIT |

Bu seçenekler farklı model ailelerini ve boyutlarını karşılaştırmak içindir; Türkçe bankacılık doğruluğu henüz ölçülmedi. Ağırlıkların indirilebilir olması aynı donanıma sığacakları anlamına gelmez. DeepSeek V3.2 büyük bir model karşılaştırmasıdır. GPT-OSS reasoning token'ları dönen metinden çıkarılsa da süre ve token bütçesi kullanır; bu yüzden Qwen'in 600 token sınırı uygulanmaz. Kesilmiş JSON yanıtı teknik hata sayılır. [GPT-OSS reasoning düzeyleri](https://huggingface.co/openai/gpt-oss-20b#reasoning-levels), [OpenRouter reasoning](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens).

## Hazır embedding profilleri

| Profil kimliği | OpenRouter modeli | Girdi profili | Model kartı / lisans |
|---|---|---|---|
| qwen3-8b | qwen/qwen3-embedding-8b | Qwen sorgu talimatı; Nebius tercihi | [Qwen3 8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B), Apache-2.0 |
| qwen3-4b | qwen/qwen3-embedding-4b | Qwen sorgu talimatı; otomatik sağlayıcı | [Qwen3 4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B), Apache-2.0 |
| bge-m3 | baai/bge-m3 | Öneksiz; dense vektör | [BGE-M3](https://huggingface.co/BAAI/bge-m3), MIT |
| multilingual-e5-large | intfloat/multilingual-e5-large | query / passage önekleri | [Multilingual E5 Large](https://huggingface.co/intfloat/multilingual-e5-large), MIT |

Varsayılan 8B/Nebius seçimi BGE-M3, E5 veya 4B isteklerine taşınmaz. Aynı model/ayarlar zaten varsayılansa menüde yinelenen seçenek gizlenir; API'de eşdeğer profiller tek deney olarak çalışır. İngilizce odaklı E5-v2 ve GTE seçenekleri bu Türkçe başlangıç listesine eklenmedi.

OpenRouter'ın [LLM kataloğu](https://openrouter.ai/api/v1/models) ve [embedding kataloğu](https://openrouter.ai/api/v1/embeddings/models) 8 Eylül 2026'da kontrol edildi. LLM kataloğunda tüm hazır seçenekler için response_format/structured_outputs alanları mevcut. Sağlayıcıya ve hesaba özel erişim, bu katalog kontrolünden ayrı olarak canlı çağrıyla doğrulanır. Qwen3 Embedding 0.6B o tarihte OpenRouter embedding kataloğunda bulunmadığı için hazır cloud listesine eklenmedi; yerel model ayarıyla kullanılabilir.

## Ölçüm ve hata davranışı

- Her deney aynı doğrulanmış vaka kopyasını ve katalog sürümünü kullanır; etiket, kaynak yanıt ve eski çalışma izi modele gönderilmez.
- Her kombinasyonun ayarları kuyruğa alınırken kopyalanır. Canlı demo ve başka deneyler ortak ayarları değiştirmez. İstekler yalnızca model profil kimliği taşır; endpoint ve anahtarlar sunucuda kalır.
- İndeks önbelleği çalışma alanı, katalog, embedding modeli, giriş profili, talimat, bağlantı ve sağlayıcı tercihini ayırır. Vektör boyutu aynı olsa da farklı modeller aynı indeksi paylaşmaz.
- Aynı embedding ile farklı LLM'ler aynı indeksi kullanır. Sorgu embedding çağrısı her vaka/kombinasyonda gerçekten çalışır; sorgu süreleri önbellekle gizlenmez.
- Yeni deneyler indeks hazırlığını `index_build_ms` olarak ayrı kaydeder. p50/p95/p99, indeks hazırlandıktan sonraki sıralı vaka süreleridir. API'ye ilk canlı isteğin soğuk başlangıcı bu ölçümle aynı değildir. Eski deneylerin protokolü değişmez; eski ve yeni gecikmeleri doğrudan kıyaslamayın.
- Çalışmalar sıra ile yürür; eşzamanlı yük testi yapılmaz. Sağlayıcı yükü, ağ ve reasoning farkları gecikmeyi etkiler. İndeks hazırlığı sonrasında ilk LLM çağrısı hâlâ sağlayıcıda soğuk olabilir.
- Bir embedding indeks hazırlığında hata verirse o modele bağlı kombinasyonlar tüm vaka paydasını koruyan hata kayıtları üretir. Aynı indeks hatası her vakada yeniden çağrı oluşturmaz; diğer modeller devam eder. Vaka sorgusu veya LLM hataları ilgili vakanın başarısızlığı sayılır. Otomatik model değiştirme yoktur.
- Tamamlanan kombinasyonlar deney sürerken görünür ve kaydedilir. En fazla 32 kombinasyon seçilebilir. Her ek kombinasyon API kullanımını artırır.

Seçilen doğruluk hedefini değerlendirmek için ilk karar doğruluğuyla birlikte kapsam dışı yanlış kabulü, tüm karar doğruluğunu ve teknik hataları inceleyin. 29 demo vakası bağımsız bir veri kümesindeki doğruluğu kanıtlamaz.

## CLI ve API

```bash
.venv/bin/python scripts/check_models.py --list-models
.venv/bin/python scripts/check_models.py --llm-only --llm-id gpt-oss-20b
.venv/bin/python scripts/check_models.py --embedding-only --embedding-id bge-m3
```

Liste komutu inference çağrısı yapmaz. Kontrol komutları sabit demo metni kullanır ve API kullanımına yol açar; accuracy ölçmez.

`GET /v1/models` kullanılabilir seçenekleri ve gizli bilgi içermeyen ayarları döndürür. `POST /v1/route` gövdesine `embedding_id` ve `llm_id` eklenir. Gönderilmeyen kimlikler `default` seçimini kullanır.

`POST /v1/evaluations` örneği:

```json
{
  "methods": ["e5", "hybrid_llm"],
  "embedding_ids": ["default", "bge-m3"],
  "llm_ids": ["default", "gpt-oss-20b"],
  "semantic_rejection": "calibrated",
  "source": "seed",
  "split": "test",
  "limit": 29
}
```

`e5` mevcut semantik yöntemin geriye uyumlu API kimliğidir. Yeni sonuç anahtarı kombinasyon kimliğidir; her sonuçta ayrıca `method`, `embedding`, `llm` ve `model` bulunur. Eski varsayılan seçimler `lexical`, `e5`, `hybrid_llm` sonuç anahtarlarını korur.

## Yeni model eklemek

[data/model-presets.json](../data/model-presets.json) dosyasına ilgili grupta bir kayıt ekleyip API'yi yeniden başlatın. Ayrı dosya için `INTENT_MODEL_CATALOG_PATH` mutlak dosya yolu verilebilir. Modelin lisansını, Türkçe kullanımını, OpenRouter model kimliğini, yapılandırılmış çıktı desteğini ve gereken embedding önekini doğrulayın. Bu dosyada API anahtarı veya endpoint bulunmaz.

On-prem/özel endpoint kullanıldığında hazır OpenRouter profilleri bağlantı gerekli durumunda görünür; mevcut sunucu modeli `default` ile kullanılabilir. Aynı on-prem endpoint'in sunduğu ek modeller için sunucu kataloğuna `connection: "configured"` ile kayıt ekleyin ve endpoint'in kabul ettiği model kimliğini kullanın. Reasoning parametresinin on-prem karşılığı `INTENT_LLM_THINKING_PARAMETER` ayarıyla belirlenir; OpenRouter profillerini on-prem servise aynen göndermeyin.
