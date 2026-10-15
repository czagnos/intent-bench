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
    "bank.card.debit": "Debit card / bank card; using a card at an ATM alone does not identify the card type.",
    "bank.digital.mobile": "Personal mobile banking / banking application.",
    "bank.digital.phone": "Telephone banking / call center. A phone device or SIM alone does not identify this channel.",
    "bank.transfer.internal": "One-off internal bank transfer; distinct from a recurring internal transfer instruction.",
    "bank.transfer.eft": "One-off EFT transfer; distinct from a scheduled EFT instruction.",
    "bank.deposit.term_try": "TRY term deposit; saying only term deposit does not identify a currency.",
    "bank.account.current_try": "TRY current account; saying only current account does not identify a currency.",
}

ACTION_RULES = {
    ("card", "daily_limit"): "This changes the daily spending cap, not the total credit card limit.",
    ("card", "online"): "Enable or disable online payment permission. Do not assume an unexplained payment failure is a permission issue.",
    ("card", "declined"): "Investigate a failed payment. An explicit request to change online permission belongs to online.",
    ("transfer", "status"): "Track an existing transfer, not a receipt request or normal delivery-time question.",
    ("transfer", "cancel"): "Cancel a transfer instruction. Select wrong_recipient when the wrong recipient is explicitly mentioned.",
    ("transfer", "wrong_recipient"): "The user must explicitly identify a wrong recipient or wrong account.",
    ("loan", "application_status"): "Track application assessment. Release of approved money belongs to disbursement.",
    ("loan", "interest"): "Ask about the interest rate. Repayment calculation for an amount and term belongs to installment_simulation.",
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
        rule = (f"Product/channel: {ALIASES.get(prefix, product + '.')} "
                "Both this product/channel and the described operation must be explicit. "
                "Do not infer an unstated product, currency, or channel. "
                "Prefer this specific definition over a general definition when both match.")
        detail = ACTION_RULES.get((parts[1], parts[3]))
        if detail:
            rule += " " + detail
        intent["selection_rule"] = rule
        parent = PARENTS.get((parts[1], parts[3]))
        if parent in by_id:
            products[parent].add(product)
            # More specific identifiers cannot bypass their operation's required information.
            intent["required_slots"] = list(by_id[parent]["required_slots"])
            intent["slot_questions"] = dict(by_id[parent]["slot_questions"])
    for iid, intent in by_id.items():
        if iid.startswith("bank."):
            continue
        rule = "Route when the described operation is clear. The workflow collects amounts, card details, references, and other execution fields."
        if iid in products:
            rule += (" If one of these products/channels is explicit, select its matching specific definition: "
                     + ", ".join(sorted(products[iid])) + ". Otherwise use this general definition; an unspecified product alone does not make the intent ambiguous.")
        if iid == "card.limit.change":
            rule += " This changes the total credit card limit; a daily spending cap is a different operation."
        intent["selection_rule"] = rule
    return result
