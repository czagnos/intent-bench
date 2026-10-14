# Intent sınırları, workflow ayrımı ve kontrollü reranker deneyi

10 Eylül 2026. Katalog/etiket geçişi: `demo-taxonomy-v2`; router promptu: `router-tr-v4-intent-only`.

15 Eylül 2026 sözleşme düzeltmesi: `router-tr-v5-array-contract`, her yanıtta `mentioned_intent_ids` için açık JSON dizisi ister; tek bir intent kesinleştiğinde değer `[]` olur. Çoklu amaç veya adaylar arasında gerçek belirsizlik varsa ilgili aday listesi korunur. Sağlayıcıya gönderilen şemada bu alan zorunludur. Mevcut endpoint uyumluluğu için `strict: false` korunur. Bu düzeltme katalog, etiket veya workflow sürümünü değiştirmez.

Aday bulma başarısı doğru son yönlendirmeyi tek başına kanıtlamaz. Bu rehber intent sınırlarını, etiket tutarlılığını ve router ile workflow sorumluluklarının ayrılmasını açıklar.

## Seçim kuralı

Ürün/kanal açıkça belirtilmiş ve işlemle eşleşiyorsa özel intent seçilir. Ürün/kanal belirtilmemişse uygun genel intent seçilir. Sırf ürün adı eksik diye netleştirme yapılmaz; para birimi veya kanal tahmin edilmez. Genel/özel ayrımı bir eşdeğerlik listesi değildir: değerlendirmede yalnız beklenen ID doğru sayılır.

| İstek | Beklenen seçim | Neden |
|---|---|---|
| “EFT'min durumunu öğrenmek istiyorum” | `bank.transfer.eft.status` | Transfer türü ve işlem açık |
| “Para gönderdim, durumunu öğrenmek istiyorum” | `transfer.status` | Transfer türü belirtilmemiş |
| “Bankamatik kartımın şifresini unuttum” | `bank.card.debit.pin_reset` | Bankamatik/banka kartı açık |
| “Telefonumu değiştirdim, SIM blokesi oldu” | `digital.device` | Cihaz değişimi telefon bankacılığı kanalı değildir |
| “Vadeli mevduat getirisini hesaplamak istiyorum” | `deposit.rate` | TL/döviz ayrımı belirtilmemiş |
| “Kartımın limitini artırmak istiyorum” | `card.limit.change` | Toplam kredi limiti günlük harcama üst sınırından ayrılır |

800 tanımın tamamında `selection_rule` bulunur. Kurallar LLM ve reranker girdisidir; embedding indeksine test etiketleri veya test soruları eklenmez. Bazı genel intent örneklerindeki özel ürün/kanal ifadeleri de genel ifadelerle değiştirilmiştir. Bu kurallar demo taksonomisinin kararıdır; müşterinin işlem kataloğuna aktarılmadan önce bankanın ürün sınırlarıyla doğrulanmalıdır.

## Router ve workflow

Router doğru akışı seçer. Modelin çıktı sözleşmesinde `slots` yoktur; adaylarda `required_slots`, konuşma durumunda `pending_slot` veya toplanmış alanlar gönderilmez. Önceki konuşma metinleri bağlam için gönderilmeye devam eder. Eski endpoint yanıtındaki `slots` alanı varsa atılır; bu bilgi workflow'a aktarılmaz.

“Kart limitimi artırmak istiyorum” ilk adımda `route → card.limit.change` üretir. Workflow daha sonra yeni limiti sorar. Bu soru intent belirsizliği olarak sayılmaz. Kullanıcı tutarı verince mevcut deterministik politika devam eder ve simülasyon onayı ister. Aynı ayrım kayıp kartın son dört hanesi ve transfer referans numarası için uygulanır. İlgili özel demo akışları genel akışın gerekli alanlarını devralır; EFT durum akışına geçmek referans adımını atlamaz.

İlk mesajda açıkça verilen hedef tutar, kartın son dört hanesi veya referans numarası workflow tarafında temkinli kurallarla alınabilir. Örneğin “limiti 5000 TL yap” hedef tutardır; “limiti 500 TL artır” fark tutarıdır ve yeni limit olarak kabul edilmez. Bu, genel amaçlı bir slot çıkarım modeli değildir; desteklenmeyen veya belirsiz değerler workflow sorusuyla toplanır.

Gerçek intent belirsizliği hâlâ `clarify` üretir. Örneğin geçici kart kapatma ile kalıcı iptal arasında ayırt edici soru sorulabilir. `clarify` yanıtında tek bir intent seçilmişse veya soru yoksa sözleşme hatası kaydedilir. Böyle bir yanıt otomatik olarak doğru yönlendirmeye çevrilmez. Teknik hata ve gereksiz netleştirme accuracy paydasında başarısız kalır.

## Veri sürümü ve mevcut kurulum

29 demo test sorusunun metni değişmedi. Beş beklenen ID, yukarıdaki genel seçim kuralına göre sürümlendi:

| Vaka | Önceki etiket | Yeni etiket |
|---|---|---|
| `seed-007` | `card.pin` | `bank.card.debit.pin_reset` |
| `seed-011` | `transfer.status` | `bank.transfer.eft.status` |
| `seed-012` | `transfer.create` | `bank.transfer.internal.create` |
| `seed-019` | `digital.password` | `bank.digital.mobile.password_reset` |
| `seed-021` | `loan.status` | `bank.loan.personal.application_status` |

Test veri sürümü `seed-specificity-v2`. Ayrı 72 kalibrasyon vakasında 12 etiket revize edildi; `calibration-seed-v1-034` sorusu konut kredisi faizini tek başına soracak şekilde sadeleştirildi. Yeni kalibrasyon sürümü `calibration-seed-specificity-v2`. Vaka ID'leri geçmişe bağlantı için korunur. Tüm etiket değişiklikleri ve gerekçeleri [geçiş kaydında](../data/demo/migrations/taxonomy-v2.json) bulunur.

API yeniden başlatılınca bir defalık atomik geçiş çalışır. Yalnız önceki demo sürümüyle birebir eşleşen tanım ve vakalar güncellenir. Kullanıcının değiştirdiği tanım, soru veya gözden geçirdiği etiket korunur. Müşteri vakaları güncellenmez. Eski veya yeni hedef intenti kullanıcı değiştirmişse ilgili demo etiketi de korunup incelemeye bırakılır. Özel kataloglar bu geçişe dahil edilmez.

Eski kataloglar, deney çıktıları ve değişen vaka kayıtlarının önceki sürümleri saklanır. **Intent kataloğu → Kataloğu denetle → Demo taksonomi sürümü** alanı geçiş sayısını, korunan kayıtları ve sürümdeki etiket değişikliklerini gösterir. Denetim indirildiğinde geçiş raporu da bulunur. API'de `GET /v1/catalog/migrations` ve `GET /v1/cases/{case_id}/versions` ile ayrıntı alınabilir. Kullanıcının sonraki etiket düzenlemeleri de vaka geçmişine kaydedilir.

Eski deneyin accuracy'si yeniden hesaplanmaz. Etiketler ve alt katalog seçme protokolü değiştiğinden, eski ve yeni yüzdelerin farkı tek başına model başarısı artışı değildir. Bu 29 vaka artık düzeltme çalışmasını yönlendiren bir regresyon kümesidir; üretim doğruluğunu değerlendirmek için ayrıca bağımsız, incelenmiş bir test kümesi gerekir.

## Katalog büyüklüklerini adil karşılaştırma

Protokol `fixed-cohort-nested-domain-v2`: aynı test, bağlam ve kalibrasyon intentleri her alt katalogda zorunlu tutulur. Deterministik diyalog hedefleri de korunur. Kalan bütçe önce çekirdek intentlerden, sonra alanlara dengeli ve sabit tohumlu diğer intentlerden doldurulur. Büyük katalog küçük kataloğu içerir; sorular ve etiketler katalog büyüklüğüne göre değiştirilmez.

Bu sayede beş yeni özel demo etiketi 48/200/800 deneyinin tamamında bulunur. Yeni 48-intent alt kümesi eski sürümdeki çekirdek 48 kümesiyle aynı değildir. Demo testinin tamamı **kalibre edilmiş semantik yöntemle** birlikte çalıştırılırsa test ve kalibrasyon hedefleri toplamda en az **53** intent gerektirir; bu durumda örneğin `64, 200, 800` seçin. İlk üç hibrit strateji ayrı semantik eşik kullanmadığından `48, 200, 800` ile çalışabilir. Müşteri veya elle düzenlenen kümelerde gereken minimum değişebilir; sunucu eksik kapsamı model çağrısından önce reddeder.

## Hangi sırayla çalıştırmalı?

Önce mevcut embedding ve LLM ile **Deneyler → Hibrit arama + LLM → Arama stratejilerini karşılaştır → İlk üç stratejiyi karşılaştır**. Yalnız bu yöntemi seçip `48, 200, 800`, 29 vaka ile dokuz kombinasyonu çalıştırın. Böylece yeni katalog ve prompt üzerinde semantik kaynak, eşit RRF ve semantik ağırlıklı RRF'yi tekrar göreceğiz. Son aday recall, doğru aday varken doğruluk, teknik hata, OOS yanlış kabul ve istek başına p95'i birlikte inceleyin. Kalibre semantik yöntemi ayrıca kullanacaksanız **Kalibrasyon** ekranında yeni katalog eşiklerini hesaplayın.

Ardından kullanılabilir bir reranker bağlayıp **Reranker açık/kapalı karşılaştır** düğmesini kullanın. Düğme aşağıdaki iki stratejiyi seçer ve ayarlarını eşitler:

| Ayar | Reranker kapalı | Reranker açık |
|---|---|---|
| Kaynak | Yalnız semantik | Yalnız semantik |
| Temsil | Tanım + örnek birlikte | Tanım + örnek birlikte |
| Kaynak / havuz / LLM adayı | 40 / 20 / 8 | 40 / 20 / 8 |
| Embedding ve LLM | Seçili ortak modeller | Seçili ortak modeller |
| Yeniden sıralama | Yok | Seçili reranker |

Tek model çifti ve üç katalog büyüklüğüyle altı kombinasyon oluşur. Karşılaştırma yalnız yeniden sıralamayı değiştirir. Aday sınırını 20'den 8'e indiren önceki üç stratejiyle farkın tamamı reranker kazancı sayılmaz. Reranker doğru intenti ilk 8'e taşıyor mu ve ek süre kabul edilebilir mi, önce bunu ölçün. Çalışma sırası ve sağlayıcı yükü gecikmeyi etkileyebilir; hız kazancı kararı için ölçümü tekrar edin.

Reranker bağlantısı yoksa düğme kapalıdır. Yerel veya HTTP bağlantısı **Model kataloğu → Reranker ekle** üzerinden yapılandırılır; [kurulum rehberi](retrieval-quality.md#reranker-bağlama). CLI için `data/reranker-comparison-profiles.json` hazırdır; özel kayıt kullanıyorsanız `reranker_id` alanını kayıt ID'siyle değiştirin.

```bash
.venv/bin/python scripts/evaluate.py --source seed --methods hybrid_llm --catalog-sizes 48 200 800 --retrieval-profiles data/reranker-comparison-profiles.json
```

## Güncelleme

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
```

API'yi yeniden başlatın. Mevcut `.env` korunur. Bu aşamada yeni embedding veya LLM anahtarı gerekmez. Gerçek model deneyi ve müşteri verisiyle bağımsız doğrulama sonraki ölçümdür; otomatik HTTP/arayüz testleri bu ölçümün yerine geçmez.

## Pitfalls

- Sağlayıcı hata testlerinde backend'in gerçek sağlayıcı önekini ve güvenli hata mesajını kullanın. Yeni bir sağlayıcı eklenince önek çevirisini ve hata metinlerini birlikte doğrulayın.

- Bağlantı testinde HTTP 200 tek başına sağlayıcının hazır olduğunu kanıtlamaz; yanıt sürümünü, model kimliğini, soru/seçenek kapsamını ve token kullanımını doğrulayın. Token toplamı için `result.usage` esas alınmalı, cevapların `input_tokens` değerleri buna tekrar eklenmemelidir. Koşullu seçenek skorlarını kalibre edilmiş karar güveni olarak kullanmayın.

- Bir sağlayıcının yanıt sözleşmesi tamamlandığında kullanılabilirlik bilgisiyle birlikte arayüz açıklamalarını, TypeScript metadata türünü ve HTTP test fixture'larını da güncelleyin. Eski "yanıt formatı bekleniyor" durumu, anahtarı kayıtlı ve çalışmaya hazır modeli hâlâ kullanılamaz gösterir; gerçek model kimliğinin canlı istek ve deney isteğine gönderildiğini doğrulayın.

- Parola alanını normal model formundan ayrı tutun; kapatma/iptal, bağlantı türü değiştirme ve başarılı kayıtta girilen anahtarı temizleyin. Düzenlemede boş alan kayıtlı anahtarı korumalı, eski anahtar formda yeniden gösterilmemelidir.

- Model kaydı ve anahtar kaydı ayrı HTTP istekleriyse ilk isteğin döndürdüğü kimliği hemen saklayıp kaydı listede gösterin. Anahtar yazımı başarısız olduğunda kısmi kayıt görünür kalmalı ve tekrar deneme aynı modeli güncellemelidir; yeniden model oluşturmak yinelenen kayıt üretir.

- Model kaydı değiştiğinde önceki bağlantı testi sonucunu hemen geçersiz kılın. Ayrı anahtar yazımı başarısız olsa bile kaydedilen bağlantının yeni kullanılabilirliğini üst ekranlardaki model seçimlerine yansıtın; eski sağlayıcının başarılı testi veya seçilebilirliği yeni bağlantı için geçerli değildir.

- Sağlayıcı adresi, protokolü ve kullanılabilirlik kontrolü kayıt, listeleme ve çıkarım aşamalarında aynı kurala uymalıdır. Bir sağlayıcıya özgü endpoint'i uyumsuz genel protokolle kaydetmeyi reddedin.

- Sağlayıcı değişirken kayıtlı anahtarı veritabanı işlemi tamamlanmadan kalıcı silmeyin. Anahtarı özel bir geçici dosyaya taşıyın, veritabanı güncellemesi reddedilirse geri yükleyin ve yalnız başarılı güncellemeden sonra silin; başarısız kayıt eski bağlantının anahtarını kaybetmemelidir.

- HTTP test taklitleri dönen veriyi serileştirmeli veya klonlamalıdır. Sunucu fixture'ı ve React state aynı değişebilir nesneyi paylaşırsa fixture güncellemesi arayüzü kod çalışmadan değiştirebilir ve eksik state güncellemesini gizleyebilir.

- Vite production build ile backend testlerini sırayla çalıştırın. Build `dist/assets` dizinini değiştirirken FastAPI `StaticFiles` kurulumu aynı dizini okursa uygulama başlatma testleri geçici dosya sistemi yarışı nedeniyle hata verebilir.

- Harici sağlayıcıyla tam reindex öncesinde gönderilecek gerçek katalog sürümünün kaynağını ve hedef embedding endpoint'ini doğrulayın. `demo` adlı çalışma alanı kullanıcı düzenlemeleri veya içe aktarılan veri içerebilir; adı, içeriğin yalnız sentetik başlangıç verisi olduğunu kanıtlamaz.

- İndeks hazırlama komutu bir deneme araması yapmamalıdır: bu, katalog hazır olsa bile fazladan sorgu embedding'i üretir ve hazırlığın kaynağını RAM gibi gösterebilir. `prepare_index()` sonucunu doğrudan raporlayın; yeni bir komut çalıştırmasının aynı nesli diskten, model çağrısı olmadan yüklediğini HTTP sınırında doğrulayın.

- İndeks hazırlığı testlerinde uygulamanın Embeddings nesnesini eksik bir taklitle değiştirmeyin; kalıcı kimlik metin biçimlendirmesini ve gerçek model ayarlarını da kullanır. Sağlayıcı hatasını HTTP sınırında simüle edip API yanıtını ve aktif katalog sürümünün korunmasını doğrulayın.

- Kalıcı embedding indeksinin kimliği credential içermez; RAM istemcisinin kimliği credential değişimini her bağlantıda izlemelidir. Yalnız kayıtlı bağlantıları ayırmak, varsayılan/env anahtarı değiştiğinde eski Authorization ile sorgu göndermeye yol açar. Disk vektörleri yeniden kullanılabilir, HTTP istemcisi güncel anahtarı almalıdır.

- Yerel API ve proxy portlarını birlikte yapılandırın. Süreç durdurmadan önce çalışma dizini ve komutunun bu projeye ait olduğunu doğrulayın; yalnız port numarasına bakarak süreç sonlandırmayın.
- Choice başına 255 seçeneğin altında kalmak TypeSafe token sınırlarına uyulduğunu kanıtlamaz. `jev-1.13`, state + tüm sorular için 64k ve state + en uzun soru için 32k sınırı tanımlar. 800 intenti dört 201-seçenekli Choice ile tam örnek/dışlama/seçim kurallarıyla gönderen ilk kontrol `400 / max_tokens_exceeded` verdi. İlk aşama yalnız ad ve açıklamaya indirildi; grup başına beş aday ve ikinci aşamanın tam Selector prompt'u korunarak yöntem tam deneyden önce sabitlendi. Limit hatasında veri sessizce kesilmez. [Sağlayıcı sınırları](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md).
- Yeni sağlayıcı eklenirken yalnız backend metadata'sını değiştirmek yeterli değildir. TypeSafe `protocol` ve `prompt_version` döndürürken OpenAI'ye özgü `reasoning`, `max_tokens` ve `response_format` alanlarını döndürmez; frontend sonucu sağlayıcıya göre ayrılan bir union ile modellemelidir. Ortak alanları kullanan ekranın çalışması eski tip tanımının doğru olduğunu kanıtlamaz.
- Geçerli TypeSafe sözleşmesi doğru intent seçimini kanıtlamaz. 17 Eylül 2026'daki dört sabit örnekli canlı kontrolde `jev-1.13.0`, “Kartımı kapatmak istiyorum” mesajını beklenen netleştirme yerine kalıcı iptale yönlendirdi. Bu hata model karşılaştırmasında korunur; başarılı HTTP/olasılık doğrulaması doğruluk başarısı olarak raporlanmaz. [Koşullar ve sonuçlar](typesafe-jev.md).
- TypeSafe aynı istekteki soruları birbirinden bağımsız değerlendirir. Netleştirme adayları için ek Choice soruları aynı çağrıda önceden sorulur; sonuçları yalnız ana karar netleştirme gerektiriyorsa kullanılır. Bir sorunun yanıtını aynı çağrıdaki başka sorunun girdisi gibi varsaymayın.
- TypeSafe Choice yanıtında seçenek üyeliği tek başına yeterli değildir: olasılıkların izinli seçenek kümesini kapsaması, sonlu ve sınırlı olması, yuvarlama toleransıyla toplamının 1 olması ve seçimin en yüksek olasılıkla tutarlı olması da doğrulanmalıdır. Geçersiz sağlayıcı yanıtı bankacılık kararına dönüştürülmez.
- JSON sözleşmesindeki `list_type` hatası tek başına alanın hangi türde geldiğini göstermez. Tanılar alan yolunu, hata kodunu ve izinli JSON türünü kaydetmeli; model yanıtı, kullanıcı içeriği veya ham değeri içermemelidir. Eksik alan ile açık `null` aynı durum değildir.
- Liste beklenen model yanıt alanlarında eksik alan ve açık `null` durumlarını sözleşme testleriyle ayırın. Bozuk yanıtı sessizce boş listeye dönüştürmeyin; başarılı HTTP yanıtı doğru veya geçerli karar anlamına gelmez.
- Tek amaç, tek intentin kesinleştiği anlamına gelmez: kart kapatma isteği geçici kapatma ile kalıcı iptal arasında belirsiz kalabilir. Boş liste talimatı yalnız kesinleşmiş tek intent veya belirtilecek aday yokluğu için geçerlidir; gerçek belirsizlik ve çoklu amaçta aday listesini silmek netleştirmeyi bozar.
