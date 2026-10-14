# Canlı demo görünümleri

Canlı demo sayfasında özet sayaçlarının altındaki **Görünüm** alanından seçim yapılır:

| Görünüm           | Gösterim                                                               |
| ----------------- | ---------------------------------------------------------------------- |
| Standart          | Mevcut konuşma, karar, adaylar ve ölçülen süreler.                     |
| Workflow haritası | Bankacılık alanları ve arama tamamlanınca açılan aday intent kartları. |
| Dairesel harita   | Merkezde giriş, iç halkada alanlar, dış halkada intentler.             |
| Intent galaksisi  | Alanlara göre gruplanmış intent noktaları.                             |
| Intent mozaiği    | Alanlara ayrılmış bir katalogda her intent için bir hücre.             |

Görünüm seçimi tarayıcıda hatırlanır. Aynı Canlı Demo içinde görünüm değiştirmek;
konuşmayı, model/embedding seçimini, devam eden isteği ve sonucu korur.
Görünüm değiştirmek veya tekrar oynatmak yeni bir model çağrısı yapmaz.
Türkçe ve İngilizce arayüz desteklenir; katalog ve konuşma içeriği özgün dilinde kalır.

## Canlı davranış

- Katalogdaki gerçek alanlar, intent kimlikleri ve sayıları kullanılır. Düzen örnek
  soruya veya belirli bir bankacılık alanına sabitlenmemiştir.
- Arama bitince aday listesi mevcut SSE bağlantısından gelir. LLM kararını beklerken
  adaylar görülebilir. Eski sunucudan ara aday verisi gelmezse nihai sonuç kullanılır.
- Seçilen intent, son karardaki kimliktir; ilk arama adayı otomatik olarak seçilmiş
  sayılmaz. Kesin yönlendirme rengi yalnızca `route` / `continue` ve geçerli workflow
  eşlemesinde kullanılır.
- Netleştirme, kapsam dışı, temsilciye aktarım, iptal ve teknik hata ayrı çıkışlardır.
  Netleştirme seçenekleri kararın kendi verilerinden gösterilir.
- Aktif workflow içindeki tutar veya onay yanıtları, o turun gerçek olaylarını
  gösterir. Arama atlandıysa önceki turun adayları taşınmaz.
- Workflow önizlemesinde gereken bilgiler, doldurulan değerler, onay bekleme durumu
  ve simülasyonun tamamlanması gösterilir. Gerçek banka işlemi yürütülmez.
- **Tüm katalog / Yakın görünüm** ile kapsam ve odak arasında geçilir. Karar ve aday
  ayrıntıları, görselin altındaki açılabilir bölümde bulunur.

Alanlar görsel gruplardır; bu görünüm yönlendiriciye yeni bir alan sınıflandırıcısı
eklemez. Yalnızca seçili harita oluşturulur. Nokta/hücre yerleri katalog kimliklerine
göre kararlıdır; her mesajda yeniden fizik simülasyonu çalışmaz. Workflow haritası
en fazla altı ilgili kartı açar; diğer görünümler genel görünümde tüm intentleri,
odakta seçilen alanı gösterir. Dar ekranlarda yerleşim yeniden hesaplanır.

## Tekrar oynatma ve ölçümler

Tamamlanan bir istekte **Tekrar oynat** gerçek işlem aşamalarını sırayla gösterir.
Gösterim süresi sunum için düzenlenmiştir; model süresi değildir. **Duraklat / Devam
et** ve görünüm değiştirme kullanılabilir. Konuşma panelindeki gerçek yanıt bekletilmez.

Yeni mesaj veya yeni konuşma önceki oynatmayı temizler. Geç gelen eski istek olayları
yeni konuşmaya uygulanmaz. Arka plana alınan sekmede tekrar oynatma duraklar.
İşletim sisteminin azaltılmış hareket tercihi çizim geçişlerine ve yol animasyonuna
uygulanır; gerçek karar ve durumlar görünmeye devam eder.

Gösterilen milisaniye değeri sunucunun `timings_ms.total` ölçümüdür. Animasyon saati
bu değeri veya deney p95 hesaplarını değiştirmez. Bu özellik bir yük testi veya
accuracy ölçümü değildir.

## API ve katalog sürümleri

`POST /v1/route` yanıtı isteğin sabitlendiği `catalog_version` değerini de döndürür.
Ara `retrieval` olayı `candidates` listesini ve `catalog_version` bilgisini taşır;
mevcut `id` / `at` / `stage` / `label` alanları korunur. Sonuç, konuşma revizyonu
kontrolünden sonra uygulanır. `pending_confirmation` son kararda gerçek onay
bekleme durumunu belirtir.

`GET /v1/catalog?version=<version>` yalnızca ilgili workspace içindeki kayıtlı
katalog sürümünü okur. Bulunamayan sürüm 404 döndürür. Başka bir kullanıcı kataloğu
değiştirse de harita, izlenen isteğin sürümünü yükler. Bu okuma canlı kataloğu
değiştirmez veya model çağrısı yapmaz.

## Güncelleme

Repo klasöründe:

```bash
npm --prefix apps/web run build
```

API'yi kendi süreç yöneticinizle yeniden başlatın.

Canlı demo → Görünüm alanı görünür. Ek API anahtarı veya yeni npm bağımlılığı gerekmez.

## Doğrulama

85 ilgili backend testi; erken aday bildirimi, SSE tekrarları, katalog sürümleri ve
workspace ayrımı, workflow/onay durumları ve mevcut kalibrasyon/model/deney akışlarını
kapsar. 14 React/jsdom testi; devam eden istekte beş görünüm arasında geçiş, tek istek
ve konuşmanın korunması, doğru adayın seçilmesi, negatif kararlar, bağlamsal devam,
tekrar oynatma, eski olayların atılması, TR/EN geçişi ve farklı ekran genişliklerinde
800 kimliğin tekil geometrik gösterimini kapsar. TypeScript/Vite production build
kontrol edilir. Gerçek sağlayıcı benchmark'ı ve gerçek tarayıcıda görsel inceleme bu
değişiklikte yapılmadı.
