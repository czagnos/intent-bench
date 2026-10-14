"""Explicit demo routing boundaries; independent of evaluation questions and predictions."""
import copy
from collections import defaultdict


PARENTS = {
    ("account", "available_balance"): "account.balance",
    ("account", "statement_range"): "account.statement",
    ("account", "remote_open"): "account.open",
    ("card", "application"): "card.apply", ("card", "lost"): "card.lost",
    ("card", "pin_reset"): "card.pin", ("card", "online"): "card.online",
    ("card", "delivery"): "card.delivery",
    ("transfer", "create"): "transfer.create", ("transfer", "status"): "transfer.status",
    ("transfer", "cancel"): "transfer.cancel", ("transfer", "wrong_recipient"): "transfer.cancel",
    ("transfer", "fee"): "transfer.fee", ("transfer", "single_limit"): "transfer.limit",
    ("transfer", "daily_limit"): "transfer.limit",
    ("loan", "application"): "loan.apply", ("loan", "application_status"): "loan.status",
    ("loan", "interest"): "loan.rate", ("loan", "total_cost"): "loan.rate",
    ("loan", "installment_simulation"): "loan.rate",
    ("loan", "installment_pay"): "loan.payment", ("loan", "early_close"): "loan.payment",
    ("digital", "password_reset"): "digital.password", ("digital", "password_lock"): "digital.password",
    ("digital", "otp_missing"): "digital.login", ("digital", "otp_expired"): "digital.login",
    ("digital", "session_timeout"): "digital.login",
    ("digital", "sim_lock"): "digital.device", ("digital", "phone_change"): "digital.device",
    ("deposit", "return_rate"): "deposit.rate", ("deposit", "return_simulation"): "deposit.rate",
    ("deposit", "term_options"): "deposit.rate", ("deposit", "close"): "account.close",
    ("deposit", "open"): "account.open",
}

ALIASES = {
    "bank.card.debit": "Banka kartı / bankamatik kartı; ATM'de kullanmak tek başına kart türünü belirtmez.",
    "bank.digital.mobile": "Bireysel mobil bankacılık / cep şubesi / bankacılık uygulaması.",
    "bank.digital.phone": "Telefon bankacılığı / çağrı merkezi. Telefon cihazı veya SIM sözcüğü tek başına bu kanalı belirtmez.",
    "bank.transfer.internal": "Tek seferlik havale; düzenli havale talimatıyla karıştırma.",
    "bank.transfer.eft": "Tek seferlik EFT; ileri tarihli EFT talimatıyla karıştırma.",
    "bank.deposit.term_try": "TL cinsinden vadeli hesap; yalnız 'vadeli mevduat' denmesi para birimini belirtmez.",
    "bank.account.current_try": "TL cinsinden vadesiz hesap; yalnız 'vadesiz hesap' denmesi para birimini belirtmez.",
}

ACTION_RULES = {
    ("card", "daily_limit"): "Günlük harcama üst sınırıdır; toplam kredi kartı limiti değişikliği değildir.",
    ("card", "online"): "İnternet kullanım iznini açma/kapama; bilinmeyen ödeme reddi nedenini izin sorunu olarak varsayma.",
    ("card", "declined"): "Başarısız ödemenin nedenini inceleme; internet kullanım izni değişikliği açıkça istenirse online kaydını seç.",
    ("transfer", "status"): "Yapılmış transferin durumunu sorgulama; dekont veya olağan ulaşma süresi isteği değildir.",
    ("transfer", "cancel"): "Transfer emrini iptal etme; yanlış alıcı açıkça belirtilirse wrong_recipient kaydını seç.",
    ("transfer", "wrong_recipient"): "Yanlış alıcı veya yanlış hesap açıkça belirtilmiş olmalı.",
    ("loan", "application_status"): "Başvuru değerlendirmesini takip etme; onaylı paranın hesaba yatması disbursement kapsamındadır.",
    ("loan", "interest"): "Faiz oranını sorma; tutar/vadeye göre taksit hesabı installment_simulation kapsamındadır.",
}


def revise_catalog(intents):
    result = copy.deepcopy(intents)
    by_id = {i["intent_id"]: i for i in result}
    products = defaultdict(set)
    for intent in result:
        parts = intent["intent_id"].split(".")
        if len(parts) != 4 or parts[0] != "bank":
            continue
        prefix = ".".join(parts[:3])
        product = intent["name"].split(" - ")[0]
        rule = (f"Ürün/kanal: {ALIASES.get(prefix, product + '.') } "
                "Bu ürün/kanal ve tanımdaki işlem birlikte belirtilmiş olmalı. "
                "Belirtilmeyen ürün, para birimi veya kanalı tahmin etme. "
                "Aynı işlemin genel kaydı da varsa bu açık ürün/kanal kaydını seç.")
        detail = ACTION_RULES.get((parts[1], parts[3]))
        if detail:
            rule += " " + detail
        intent["selection_rule"] = rule
        parent = PARENTS.get((parts[1], parts[3]))
        if parent in by_id:
            products[parent].add(product)
            # A more specific identifier must not bypass its operation's required information.
            intent["required_slots"] = list(by_id[parent]["required_slots"])
            intent["slot_questions"] = dict(by_id[parent]["slot_questions"])
    for iid, intent in by_id.items():
        if iid.startswith("bank."):
            continue
        rule = "Tanımdaki işlem belirliyse bu akışa yönlendir. İşlem tutarı, kart numarası veya referans gibi bilgiler akışta tamamlanır."
        if iid in products:
            rule += (" Aynı işlem için şu ürün/kanallardan biri açıkça belirtilirse ilgili özel kaydı seç: "
                     + ", ".join(sorted(products[iid])) + ". Ürün/kanal belirtilmemişse bu genel kaydı seç; ürün seçtirmek için intenti belirsiz sayma.")
        if iid == "card.limit.change":
            rule += " Toplam kredi kartı limiti değişikliğidir; günlük harcama sınırı ayrı işlemdir."
        intent["selection_rule"] = rule
    return result
