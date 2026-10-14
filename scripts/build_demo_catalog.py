"""Build the 800-intent illustrative bank catalog from explicit product/action pairs.

These are synthetic routing definitions, not a real bank's product commitments or
gold customer labels. Scope rules are versioned independently from historical results.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
from app.demo_taxonomy import revise_catalog

# Each request has a distinct operation or information need. Products qualify the
# operation so that near-neighbour confusion can be measured as the catalog grows.
# (action id, short label, question, alternative utterance, transaction)
PROFILES = {
    "account": [
        ("eligibility", "Açılış koşulları", "kimler hesap açabilir?", "hesap açmaya uygun olup olmadığımı öğrenmek istiyorum", False),
        ("documents", "Açılış belgeleri", "açılışta hangi belgeler gerekiyor?", "başvuru için gereken evrak listesini paylaşır mısınız", False),
        ("remote_open", "Uzaktan hesap açılışı", "şubeye gitmeden hesap açabilir miyim?", "uzaktan hesap açılış sürecini başlatmak istiyorum", True),
        ("application_status", "Açılış başvurusu takibi", "hesap açılış başvurum ne durumda?", "bekleyen hesap açılış başvurumun sonucunu sorguluyorum", False),
        ("maintenance_fee", "Hesap işletim ücreti", "hesap işletim ücreti alınıyor mu?", "hesabın düzenli bakım masraflarını öğrenebilir miyim", False),
        ("minimum_balance", "Asgari bakiye koşulu", "asgari ne kadar bakiye bulundurmalıyım?", "hesapta tutulması gereken minimum tutarı soruyorum", False),
        ("available_balance", "Kullanılabilir bakiye", "kullanılabilir bakiyem ne kadar?", "işleme açık hesap bakiyemi gösterir misiniz", False),
        ("blocked_balance", "Blokeli bakiye nedeni", "bakiyemin bir kısmı neden blokeli?", "hesaptaki blokajın sebebini öğrenmek istiyorum", False),
        ("account_certificate", "Hesap sahipliği belgesi", "hesap sahipliği belgesini nasıl alabilirim?", "adıma kayıtlı olduğunu gösteren hesap belgesini talep ediyorum", False),
        ("statement_range", "Tarihli hesap dökümü", "belirli iki tarih arasındaki dökümü alabilir miyim?", "seçtiğim tarih aralığı için hesap hareketlerini istiyorum", False),
        ("account_alias", "Hesap adı değiştirme", "hesabıma verdiğim kısa adı değiştirebilir miyim?", "hesabımın uygulamadaki takma adını güncellemek istiyorum", True),
        ("notification", "Hareket bildirimi ayarı", "para giriş çıkış bildirimlerini nasıl açarım?", "bu hesaptaki hareketler için bildirim almak istiyorum", True),
        ("dormant", "Hareketsiz hesap durumu", "uzun süredir kullanmadığım hesap aktif mi?", "hareketsiz kalan hesabımın durumunu kontrol etmek istiyorum", False),
        ("authority", "Hesap yetkileri", "hesap üzerinde kimler işlem yapabilir?", "hesabın kullanım ve temsil yetkilerini öğrenmek istiyorum", False),
        ("closure_conditions", "Kapanış koşulları", "hesabı kapatmanın koşulları nelerdir?", "hesap kapatmadan önce tamamlamam gerekenleri soruyorum", False),
        ("closure_status", "Kapanış talebi takibi", "hesap kapama talebim sonuçlandı mı?", "verdiğim hesap kapatma talebinin durumunu öğrenmek istiyorum", False),
    ],
    "loan": [
        ("eligibility", "Başvuru uygunluğu", "başvuru koşulları nelerdir?", "bu krediye başvurmaya uygun olup olmadığımı öğrenmek istiyorum", False),
        ("documents", "Başvuru belgeleri", "hangi başvuru belgeleri gerekiyor?", "kredi başvurusunda sunacağım evrak listesini soruyorum", False),
        ("application", "Yeni başvuru", "yeni başvuru yapabilir miyim?", "bu kredi için başvuru sürecini başlatmak istiyorum", True),
        ("application_status", "Başvuru sonucu", "başvurumun sonucu nedir?", "verdiğim kredi başvurusunun hangi aşamada olduğunu soruyorum", False),
        ("interest", "Faiz oranı bilgisi", "uygulanan faiz oranını öğrenebilir miyim?", "bu kredinin faiz oranlarını soruyorum", False),
        ("total_cost", "Toplam maliyet dökümü", "faiz ve masraflar dahil toplam maliyet nedir?", "bu kredinin tüm maliyet kalemlerini görmek istiyorum", False),
        ("installment_simulation", "Taksit hesaplama", "tutar ve vadeye göre taksit hesabı yapabilir miyim?", "bu kredi için örnek ödeme planı oluşturmak istiyorum", False),
        ("collateral", "Teminat koşulları", "hangi teminatlar istenir?", "bu kredide teminat gerekip gerekmediğini soruyorum", False),
        ("disbursement", "Kullandırım durumu", "onaylanan tutar ne zaman hesabıma geçer?", "onaylı kredimin kullandırımını takip etmek istiyorum", False),
        ("installment_pay", "Taksit ödeme", "sıradaki taksitimi ödeyebilir miyim?", "bu krediye ait taksit ödemesini yapmak istiyorum", True),
        ("due_date", "Ödeme günü değişikliği", "taksit ödeme gününü değiştirebilir miyim?", "bu kredide taksit tarihimin değiştirilmesini talep ediyorum", True),
        ("partial_prepayment", "Ara ödeme", "anaparaya ara ödeme yapabilir miyim?", "bu krediye kısmi erken ödeme yapmak istiyorum", True),
        ("early_close", "Erken kapama tutarı", "bugün tamamen kapatırsam ne kadar öderim?", "bu kredinin erken kapama tutarını sorguluyorum", False),
        ("overdue", "Gecikmiş taksit sorgusu", "geciken taksitlerim hangileri?", "bu krediye ait gecikmiş borcumu görmek istiyorum", False),
        ("restructure", "Yapılandırma talebi", "ödemelerimi yeniden yapılandırabilir miyim?", "bu kredi için yeni ödeme planı talep ediyorum", True),
        ("debt_clearance", "Borcu yoktur belgesi", "kapattığım kredi için borcu yoktur belgesi alabilir miyim?", "bu kredinin bittiğini gösteren belgeyi talep ediyorum", False),
    ],
    "card": [
        ("eligibility", "Başvuru koşulları", "başvuru şartları nelerdir?", "bu kartı kimlerin alabileceğini öğrenmek istiyorum", False),
        ("application", "Kart başvurusu", "yeni kart başvurusu yapabilir miyim?", "bu kart için başvuru başlatmak istiyorum", True),
        ("application_status", "Başvuru takibi", "kart başvurum ne durumda?", "bu karta yaptığım başvurunun sonucunu sorguluyorum", False),
        ("delivery", "Teslimat takibi", "kartımın teslimatı hangi aşamada?", "bu kartın kurye ve teslimat durumunu öğrenmek istiyorum", False),
        ("activate", "İlk kullanım aktivasyonu", "yeni gelen kartı nasıl aktive ederim?", "bu kartı ilk kez kullanıma açmak istiyorum", True),
        ("pin_reset", "PIN yenileme", "unuttuğum kart PIN kodunu nasıl yenilerim?", "bu kart için yeni PIN belirlemek istiyorum", True),
        ("contactless", "Temassız kullanım ayarı", "temassız ödeme özelliğini nasıl değiştiririm?", "bu kartın temassız kullanım iznini ayarlamak istiyorum", True),
        ("online", "İnternet kullanım izni", "internet alışverişi iznini nasıl değiştiririm?", "bu kartın çevrim içi harcama iznini güncellemek istiyorum", True),
        ("international", "Yurt dışı kullanım izni", "yurt dışında kullanım iznini açabilir miyim?", "bu kartın yurt dışı işlemlerine izin vermek istiyorum", True),
        ("daily_limit", "Günlük harcama sınırı", "günlük harcama sınırı belirleyebilir miyim?", "bu kart için günlük kullanım sınırını ayarlamak istiyorum", True),
        ("lost", "Kayıp kart bildirimi", "kaybettiğim kartı güvene alabilir miyiz?", "bu kartı kaybettim, kayıp bildirimi yapmak istiyorum", True),
        ("damaged", "Hasarlı kart yenileme", "bozulan kartımı nasıl yenileyebilirim?", "bu kart fiziksel olarak zarar gördü, yenisini talep ediyorum", True),
        ("expiry", "Son kullanma tarihi yenilemesi", "süresi dolan kart ne zaman yenilenir?", "bu kartın son kullanma tarihi nedeniyle yenilenmesini soruyorum", False),
        ("declined", "Reddedilen işlem incelemesi", "yaptığım ödeme neden reddedildi?", "bu kartla yaptığım başarısız işlemin nedenini öğrenmek istiyorum", False),
        ("refund_status", "Harcama iadesi takibi", "işyerinin yaptığı iade karta ne zaman yansır?", "bu karta beklediğim harcama iadesini takip etmek istiyorum", False),
        ("transaction_alert", "Harcama bildirimi", "harcama bildirimlerini açabilir miyim?", "bu kartla ödeme yapıldığında bildirim almak istiyorum", True),
    ],
    "transfer": [
        ("create", "Yeni transfer", "yeni para gönderimi başlatabilir miyim?", "bu yöntemle para göndermek istiyorum", True),
        ("recipient_fields", "Alıcı bilgileri", "alıcıdan hangi bilgileri almalıyım?", "bu transfer için gereken alıcı bilgilerini soruyorum", False),
        ("iban_validation", "Alıcı hesap kontrolü", "alıcı hesap bilgisi neden kabul edilmiyor?", "bu transferde alıcı hesabı doğrulanmıyor", False),
        ("fee", "İşlem ücreti", "ne kadar işlem ücreti alınır?", "bu gönderimin komisyonunu öğrenmek istiyorum", False),
        ("single_limit", "Tek işlem limiti", "tek seferde en fazla ne kadar gönderebilirim?", "bu yöntemin işlem başına tutar sınırını soruyorum", False),
        ("daily_limit", "Günlük toplam limit", "gün içinde toplam ne kadar gönderebilirim?", "bu yöntemin günlük toplam gönderim sınırını öğrenmek istiyorum", False),
        ("hours", "İşlem saatleri", "hangi saatlerde işlem yapabilirim?", "bu para gönderiminin hizmet saatlerini soruyorum", False),
        ("arrival_time", "Tahmini ulaşma süresi", "gönderim alıcıya ne kadar sürede ulaşır?", "bu transfer yönteminin olağan ulaşma süresini öğrenmek istiyorum", False),
        ("status", "Mevcut transfer takibi", "gönderdiğim paranın durumu nedir?", "bu yöntemle yaptığım gönderimi takip etmek istiyorum", False),
        ("receipt", "Transfer dekontu", "yaptığım işlemin dekontunu alabilir miyim?", "bu transferin işlem belgesini talep ediyorum", False),
        ("cancel", "İptal talebi", "verdiğim transfer emrini iptal edebilir miyim?", "bu para gönderiminin iptalini talep ediyorum", True),
        ("wrong_recipient", "Yanlış alıcıya gönderim", "yanlış hesaba gönderdiğim para için ne yapmalıyım?", "bu transferde alıcıyı yanlış seçtim, geri çağırma talebim var", True),
        ("returned", "İade edilen transfer", "gönderdiğim para neden geri döndü?", "bu transferin iade edilme nedenini sorguluyorum", False),
        ("pending_review", "İncelemede bekleyen transfer", "işlemim neden incelemede bekliyor?", "bu para gönderiminin inceleme durumunu öğrenmek istiyorum", False),
        ("duplicate", "Mükerrer transfer", "aynı gönderim iki kez yapılmış, ne yapabilirim?", "bu yöntemle iki defa para gönderdim, mükerrer işlem bildiriyorum", True),
        ("save_recipient", "Kayıtlı alıcı", "bu alıcıyı sonraki gönderimler için kaydedebilir miyim?", "bu transfer alıcısını kayıtlı alıcılarıma eklemek istiyorum", True),
    ],
    "investment": [
        ("eligibility", "İşlem yetkisi koşulları", "işlem yapabilmek için hangi koşullar gerekiyor?", "bu yatırım aracında işlem yapma koşullarını öğrenmek istiyorum", False),
        ("risk_information", "Risk bilgisi", "ürünün temel riskleri nelerdir?", "bu yatırım aracının risk açıklamasını okumak istiyorum", False),
        ("agreement", "Sözleşme ve onaylar", "hangi sözleşmeleri onaylamam gerekiyor?", "bu yatırım işlemleri için gereken sözleşmeleri soruyorum", False),
        ("price", "Fiyat sorgusu", "güncel fiyatı nereden görebilirim?", "bu yatırım aracının fiyat bilgisini görmek istiyorum", False),
        ("trading_hours", "İşlem saatleri", "alım satım saatleri nelerdir?", "bu yatırım aracının emir kabul saatlerini öğrenmek istiyorum", False),
        ("minimum_order", "Asgari emir tutarı", "minimum emir miktarı ne kadar?", "bu üründe en az hangi tutarla işlem yapılabildiğini soruyorum", False),
        ("commission", "İşlem komisyonu", "alım satım komisyonu nedir?", "bu yatırım aracındaki işlem masrafını öğrenmek istiyorum", False),
        ("buy", "Alım emri", "alım emri verebilir miyim?", "bu yatırım aracı için satın alma emri oluşturmak istiyorum", True),
        ("sell", "Satım emri", "satım emri verebilir miyim?", "elimdeki bu yatırım aracını satmak için emir vermek istiyorum", True),
        ("order_status", "Emir durumu", "verdiğim emir gerçekleşti mi?", "bu yatırım aracına ait emrimin durumunu sorguluyorum", False),
        ("cancel_order", "Emir iptali", "bekleyen emrimi iptal edebilir miyim?", "bu üründeki açık emrimin iptalini istiyorum", True),
        ("settlement", "Takas ve valör", "işlem sonrası nakit ne zaman kullanılabilir?", "bu yatırım işleminin takas ve valör süresini soruyorum", False),
        ("position", "Portföydeki miktar", "portföyümde ne kadar bulunuyor?", "bu yatırım aracındaki mevcut pozisyonumu görmek istiyorum", False),
        ("profit_loss", "Gerçekleşmiş kâr zarar", "gerçekleşmiş kâr zararımı nasıl görebilirim?", "bu yatırım aracındaki tamamlanan işlemlerimin sonucunu görmek istiyorum", False),
        ("tax_document", "Vergi kesintisi belgesi", "işlemlerimin vergi kesintisi belgesini alabilir miyim?", "bu yatırım aracına ait kesinti dökümünü talep ediyorum", False),
        ("statement", "İşlem ekstresi", "belirli dönemin işlem ekstresini alabilir miyim?", "bu üründeki alım satımlarımın dönemsel dökümünü istiyorum", False),
    ],
    "insurance": [
        ("quote", "Teklif talebi", "yeni teklif alabilir miyim?", "bu sigorta için teklif oluşturmak istiyorum", True),
        ("eligibility", "Sigortalanma koşulları", "sigortalanma koşulları nelerdir?", "bu poliçeden yararlanma şartlarını öğrenmek istiyorum", False),
        ("documents", "Başvuru belgeleri", "hangi belgeleri sunmalıyım?", "bu poliçe başvurusu için evrak listesini soruyorum", False),
        ("coverage", "Teminat kapsamı", "hangi durumlar teminat altında?", "bu sigortanın kapsadığı riskleri öğrenmek istiyorum", False),
        ("exclusions", "Teminat dışı durumlar", "hangi durumlar kapsam dışında kalır?", "bu poliçenin istisnalarını öğrenmek istiyorum", False),
        ("premium", "Prim tutarı", "ödenecek prim tutarı nedir?", "bu sigortanın prim bedelini sorguluyorum", False),
        ("premium_pay", "Prim ödeme", "prim ödemesini yapabilir miyim?", "bu poliçenin primini ödemek istiyorum", True),
        ("policy_copy", "Poliçe kopyası", "poliçe belgesini indirebilir miyim?", "bu sigortaya ait poliçe kopyasını talep ediyorum", False),
        ("validity", "Poliçe geçerliliği", "poliçem hangi tarihe kadar geçerli?", "bu sigortanın başlangıç ve bitiş tarihini sorguluyorum", False),
        ("renew", "Yenileme talebi", "süresi biten poliçeyi yenileyebilir miyim?", "bu sigortayı yeni dönem için yenilemek istiyorum", True),
        ("cancel", "İptal talebi", "poliçeyi iptal etmek için ne yapmalıyım?", "bu sigorta poliçesinin iptalini talep ediyorum", True),
        ("refund", "Prim iadesi takibi", "iptal sonrası prim iadem ne durumda?", "bu poliçe için beklediğim prim iadesini sorguluyorum", False),
        ("claim_create", "Hasar bildirimi", "hasar dosyası açabilir miyim?", "bu sigorta kapsamında hasar bildirimi yapmak istiyorum", True),
        ("claim_documents", "Hasar dosyası belgeleri", "hasar dosyam için hangi evraklar gerekiyor?", "bu poliçedeki hasar talebinin eksik belgelerini öğrenmek istiyorum", False),
        ("claim_status", "Hasar dosyası takibi", "hasar dosyam hangi aşamada?", "bu sigortadaki açık hasar talebimin durumunu sorguluyorum", False),
        ("insured_update", "Poliçe bilgisi düzeltme", "poliçedeki bilgilerimi düzeltebilir miyim?", "bu sigorta belgesindeki hatalı bilgiyi güncellemek istiyorum", True),
    ],
    "merchant": [
        ("application", "Üye işyeri başvurusu", "işyerim için başvuru yapabilir miyim?", "bu tahsilat hizmetini işletmemde kullanmak için başvurmak istiyorum", True),
        ("documents", "Başvuru evrakları", "işyerimden hangi belgeler isteniyor?", "bu tahsilat hizmetine başvuru evraklarını öğrenmek istiyorum", False),
        ("status", "Başvuru takibi", "işyeri başvurum ne durumda?", "bu tahsilat hizmetine yaptığım başvuruyu takip etmek istiyorum", False),
        ("activation", "Hizmet aktivasyonu", "onaylanan hizmeti nasıl aktive ederim?", "bu tahsilat kanalını işyerim için kullanıma açmak istiyorum", True),
        ("commission", "Komisyon oranı", "işyerime uygulanan komisyon nedir?", "bu tahsilat kanalının işyeri komisyonunu sorguluyorum", False),
        ("settlement", "Tahsilat hesaba geçişi", "satış tutarları hesabıma ne zaman geçer?", "bu kanaldaki tahsilatların valörünü öğrenmek istiyorum", False),
        ("installment", "Taksitli satış koşulları", "taksitli satış koşulları nelerdir?", "bu tahsilat kanalında taksit seçeneklerini öğrenmek istiyorum", False),
        ("limits", "İşlem limitleri", "tahsilat tutarı sınırları nelerdir?", "bu kanaldaki işyeri işlem limitlerini sorguluyorum", False),
        ("declined", "Başarısız tahsilat", "müşteri ödemesi neden reddedildi?", "bu kanalda başarısız olan tahsilatı inceletmek istiyorum", False),
        ("refund", "Satış iadesi", "aldığım ödemeyi müşteriye iade edebilir miyim?", "bu tahsilat kanalındaki satış için iade başlatmak istiyorum", True),
        ("void", "Satış iptali", "henüz kesinleşmemiş satışı iptal edebilir miyim?", "bu kanaldaki bekleyen satış işlemini iptal etmek istiyorum", True),
        ("chargeback", "Ters ibraz bildirimi", "gelen harcama itirazını nereden takip ederim?", "bu kanala ait ters ibraz bildirimini incelemek istiyorum", False),
        ("reconciliation", "Mutabakat raporu", "satış ve tahsilat mutabakatını alabilir miyim?", "bu kanal için mutabakat raporunu görmek istiyorum", False),
        ("statement", "İşyeri ekstresi", "işyeri ekstresini indirebilir miyim?", "bu tahsilat kanalının dönemsel işyeri dökümünü istiyorum", False),
        ("bank_account", "Tahsilat hesabı değişikliği", "ödemelerin yatacağı hesabı değiştirebilir miyim?", "bu hizmetin bağlı olduğu tahsilat hesabını güncellemek istiyorum", True),
        ("termination", "Hizmet fesih talebi", "işyeri sözleşmesini nasıl sonlandırırım?", "bu tahsilat hizmetinin kapatılmasını talep ediyorum", True),
    ],
    "digital": [
        ("enrollment", "Kullanıcı kaydı", "ilk kullanım kaydını nasıl oluştururum?", "bu kanalı kullanabilmek için kullanıcı kaydı açmak istiyorum", True),
        ("login_id", "Müşteri numarası bulma", "girişte kullanacağım müşteri numarasını nasıl öğrenirim?", "bu kanal için giriş kimliğimi öğrenmek istiyorum", False),
        ("password_reset", "Şifre yenileme", "giriş şifremi unuttum, nasıl yenilerim?", "bu kanaldaki şifremi yeniden belirlemek istiyorum", True),
        ("password_lock", "Şifre blokesi kaldırma", "hatalı denemelerden sonra şifrem neden kilitlendi?", "bu kanaldaki giriş blokemin kaldırılmasını istiyorum", True),
        ("otp_missing", "Doğrulama kodu ulaşmaması", "giriş doğrulama kodu neden gelmiyor?", "bu kanala giriş için beklediğim tek kullanımlık kod ulaşmadı", False),
        ("otp_expired", "Doğrulama kodu süresi", "doğrulama kodunun süresi dolduğunda ne yapmalıyım?", "bu kanalda süresi geçen doğrulama kodu nedeniyle giriş yapamıyorum", False),
        ("phone_change", "Telefon numarası güncelleme", "kayıtlı telefonumu nasıl güncellerim?", "bu kanalın doğrulama için kullandığı numarayı değiştirmek istiyorum", True),
        ("sim_lock", "SIM güvenlik blokesi", "SIM değişikliği sonrası erişimimi nasıl açarım?", "bu kanaldaki SIM kart değişikliği blokesini kaldırmak istiyorum", True),
        ("session_timeout", "Oturumun erken kapanması", "oturumum neden sürekli kapanıyor?", "bu kanalı kullanırken bağlantım erken sonlanıyor", False),
        ("suspicious_login", "Şüpheli erişim bildirimi", "tanımadığım bir giriş için ne yapmalıyım?", "bu kanalda bana ait olmayan bir erişimi bildiriyorum", True),
        ("transaction_limit", "Kanal işlem limiti", "kanala özel günlük işlem sınırım nedir?", "bu kanaldan yapabileceğim işlemlerin limitlerini soruyorum", False),
        ("authorization", "İşlem yetkisi sorunu", "işlem yetkim olmadığı uyarısını neden alıyorum?", "bu kanalda izin verilmeyen işlem için yetki durumumu soruyorum", False),
        ("service_availability", "Hizmet kesintisi sorgusu", "şu anda hizmet kesintisi var mı?", "bu kanaldaki erişim sorununun genel arıza olup olmadığını soruyorum", False),
        ("supported_operations", "Desteklenen işlemler", "hangi bankacılık işlemlerini yapabilirim?", "bu kanalda sunulan işlem listesini öğrenmek istiyorum", False),
        ("access_close", "Kanal erişimi kapatma", "bu kanala erişimimi kapatabilir miyim?", "bu bankacılık kanalının kullanımını durdurmak istiyorum", True),
        ("access_reopen", "Kanal erişimi yeniden açma", "kapalı erişimimi yeniden açabilir miyim?", "bu kanalı tekrar kullanmak için erişim açılışı talep ediyorum", True),
    ],
    "deposit": [
        ("open", "Hesap açma", "yeni hesap açabilir miyim?", "bu mevduat ürünü için hesap açmak istiyorum", True),
        ("minimum", "Açılış alt limiti", "hesap açılışında minimum tutar nedir?", "bu mevduat ürününe başlamak için gereken tutarı soruyorum", False),
        ("term_options", "Vade seçenekleri", "hangi vadeler seçilebilir?", "bu mevduat ürününün vade seçeneklerini öğrenmek istiyorum", False),
        ("return_rate", "Getiri oranı bilgisi", "uygulanan getiri oranı nasıl belirlenir?", "bu mevduat ürününün oran bilgisini soruyorum", False),
        ("return_simulation", "Getiri hesaplama", "tutar ve vadeye göre getiriyi nasıl hesaplarım?", "bu mevduat ürünü için örnek getiri hesabı görmek istiyorum", False),
        ("maturity_date", "Vade sonu tarihi", "mevcut hesabımın vadesi ne zaman bitiyor?", "bu mevduat hesabının vade bitişini öğrenmek istiyorum", False),
        ("renewal", "Otomatik yenileme tercihi", "vade sonunda otomatik yenilemeyi ayarlayabilir miyim?", "bu mevduat hesabının yenileme talimatını değiştirmek istiyorum", True),
        ("payout_account", "Vade sonu ödeme hesabı", "vade sonunda para hangi hesaba geçecek?", "bu mevduatın vade sonu aktarım hesabını sorguluyorum", False),
        ("early_withdrawal", "Vade öncesi çekim koşulları", "vade dolmadan para çekersem ne olur?", "bu mevduatta erken çekimin koşullarını öğrenmek istiyorum", False),
        ("partial_withdrawal", "Kısmi çekim talebi", "bakiyenin bir kısmını çekebilir miyim?", "bu mevduat hesabından kısmi çekim talep ediyorum", True),
        ("add_funds", "Para ekleme koşulları", "vade devam ederken para ekleyebilir miyim?", "bu mevduat hesabına ilave tutar yatırma koşullarını soruyorum", False),
        ("tax_deduction", "Kesinti dökümü", "getirimden yapılan kesintileri görebilir miyim?", "bu mevduat hesabının kesinti dökümünü istiyorum", False),
        ("net_return", "Gerçekleşmiş net getiri", "tamamlanan dönemde net ne kadar kazandım?", "bu mevduatta gerçekleşen dönem sonu net getiriyi sorguluyorum", False),
        ("account_statement", "Mevduat hesap belgesi", "mevduat hesap belgesini alabilir miyim?", "bu mevduatın tutar ve vade bilgilerini içeren belgeyi talep ediyorum", False),
        ("guarantee", "Güvence kapsamı bilgisi", "mevduat güvencesinin koşulları nelerdir?", "bu mevduat ürününün güvence kapsamı açıklamasını istiyorum", False),
        ("close", "Mevduat kapama talebi", "mevduat hesabını kapatabilir miyim?", "bu mevduat hesabının kapatılmasını talep ediyorum", True),
    ],
}

FAMILIES = {
    "account": ("Hesaplar", [("current_try", "Vadesiz TL hesabı"), ("current_fx", "Vadesiz döviz hesabı"), ("joint", "Ortak hesap"), ("child", "Çocuk hesabı"), ("salary", "Maaş hesabı"), ("nonresident", "Yurt dışında yerleşik müşteri hesabı")]),
    "loan": ("Krediler", [("personal", "İhtiyaç kredisi"), ("mortgage", "Konut kredisi"), ("vehicle", "Taşıt kredisi"), ("education", "Eğitim kredisi"), ("debt_transfer", "Borç transfer kredisi"), ("business_investment", "Ticari yatırım kredisi")]),
    "card": ("Kartlar", [("virtual", "Sanal kredi kartı"), ("supplementary", "Ek kredi kartı"), ("debit", "Banka kartı"), ("business", "Ticari kredi kartı")]),
    "transfer": ("Ödemeler", [("fast", "FAST transferi"), ("eft", "EFT transferi"), ("internal", "Havale transferi"), ("swift", "SWIFT transferi"), ("scheduled_eft", "İleri tarihli EFT"), ("recurring_internal", "Düzenli havale talimatı")]),
    "investment": ("Yatırım", [("equity", "Hisse senedi"), ("etf", "Borsa yatırım fonu"), ("money_market", "Para piyasası fonu"), ("eurobond", "Eurobond"), ("government_bond", "Devlet tahvili"), ("futures", "Vadeli işlem sözleşmesi")]),
    "insurance": ("Sigorta", [("dask", "DASK poliçesi"), ("home", "Konut sigortası"), ("motor", "Kasko poliçesi"), ("travel", "Seyahat sağlık sigortası")]),
    "merchant": ("Üye işyeri", [("physical_pos", "Fiziksel POS"), ("virtual_pos", "Sanal POS"), ("softpos", "Cep telefonundan temassız tahsilat"), ("payment_link", "Ödeme linki ile tahsilat"), ("marketplace", "Pazaryeri tahsilat hizmeti")]),
    "digital": ("Dijital bankacılık", [("mobile", "Mobil bankacılık"), ("web", "İnternet bankacılığı"), ("phone", "Telefon bankacılığı"), ("corporate_web", "Kurumsal internet bankacılığı"), ("corporate_mobile", "Kurumsal mobil bankacılık")]),
    "deposit": ("Mevduat", [("term_try", "Vadeli TL hesabı"), ("term_fx", "Vadeli döviz hesabı"), ("savings", "Birikimli mevduat hesabı"), ("participation", "Katılma hesabı"), ("term_gold", "Vadeli altın hesabı")]),
}

# Some operations do not apply to a virtual card. Replace these with real virtual-card requests.
VIRTUAL_OVERRIDES = {
    "delivery": ("card_details", "Kart bilgilerini görüntüleme", "kart numarası ve güvenlik kodunu nereden görürüm?", "bu kartın ödeme bilgilerini görüntülemek istiyorum", False),
    "pin_reset": ("security_code", "Güvenlik kodu sorunu", "güvenlik kodum neden kabul edilmiyor?", "bu kartla ödeme yaparken güvenlik kodu hatası alıyorum", False),
    "contactless": ("wallet", "Dijital cüzdan uyumluluğu", "dijital cüzdana ekleyebilir miyim?", "bu kartın dijital cüzdan uyumluluğunu soruyorum", False),
    "lost": ("compromised", "Kart bilgisi sızıntısı", "kart bilgilerim başkasının eline geçtiyse ne yapmalıyım?", "bu kartın bilgileri ifşa oldu, güvenlik bildirimi yapmak istiyorum", True),
    "damaged": ("regenerate", "Kart numarası yenileme", "kart numaramı yeniden oluşturabilir miyim?", "bu kart için yeni bir kart numarası oluşturmak istiyorum", True),
}


def build():
    result = json.loads((ROOT / "data/demo/catalog-core.json").read_text())
    for profile, (domain, families) in FAMILIES.items():
        for family, product in families:
            actions = [VIRTUAL_OVERRIDES.get(a[0], a) if profile == "card" and family == "virtual" else a for a in PROFILES[profile]]
            prefix = f"bank.{profile}.{family}"
            for index, (action, label, question, alternative, transaction) in enumerate(actions):
                iid = f"{prefix}.{action}"
                neighbours = [actions[j] for j in (index-1, index+1) if 0 <= j < len(actions)]
                result.append({
                    "intent_id": iid, "name": f"{product} - {label}", "domain": domain,
                    "description": f"{product} kapsamında {label.lower()} isteği. Kullanıcı bu ürünü veya kanalı açıkça belirtir. {question[0].upper()+question[1:]}",
                    "examples": [f"{product} için {question}", f"{alternative[0].upper()+alternative[1:]}: {product}."],
                    "exclusions": [f"Ürün belirtilmeden sorulan genel {domain.lower()} talepleri.", *[f"{product}: {a[1].lower()}." for a in neighbours]],
                    "confusable_with": [f"{prefix}.{a[0]}" for a in neighbours],
                    "workflow_id": "workflow." + iid, "required_slots": [], "slot_questions": {},
                    "channels": ["chat", "voice"], "kind": "transaction" if transaction else "information",
                })
    assert len(result) == 800
    assert len({i["intent_id"] for i in result}) == 800
    return revise_catalog(result)


if __name__ == "__main__":
    destination = ROOT / "data/demo/catalog.json"
    destination.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n")
    print(f"{destination}: 800 intents (48 core + 752 illustrative product/action intents)")
