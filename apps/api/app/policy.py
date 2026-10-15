import copy
import re

from .contracts import Proposal
from .retrieval import normalize, tokens


def amount(text):
    text = normalize(text).strip()
    text = re.split(r"\bdegil\b", text)[-1].strip()
    text = re.sub(r"\b(tl|try|lira|olsun|yok|usd|eur|dollars?|euros?|pounds?)\b", "", text).strip(" .,!$")
    if re.fullmatch(r"\d[\d., ]*", text):
        compact = text.replace(" ", "")
        # Accept integer amounts in English or Turkish notation; never round decimals.
        if re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.0{1,2})?", compact):
            number = compact.replace(",", "")
        elif re.fullmatch(r"(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,0{1,2})?", compact):
            number = compact.replace(".", "").replace(",", ".")
        else:
            return None
        try:
            value = float(number)
            return str(int(value)) if value.is_integer() and value > 0 else None
        except ValueError:
            return None
    numbers = {"sifir": 0, "bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10, "yirmi": 20, "otuz": 30, "kirk": 40, "elli": 50, "altmis": 60, "yetmis": 70, "seksen": 80, "doksan": 90}
    numbers.update({"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
                    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
                    "seventy": 70, "eighty": 80, "ninety": 90})
    total, block = 0, 0
    words = tokens(text)
    for word in words:
        if word in numbers:
            block += numbers[word]
        elif word in ("yuz", "hundred"):
            block = (block or 1)*100
        elif word in ("bin", "milyon", "thousand", "million"):
            total += (block or 1) * (1000 if word in ("bin", "thousand") else 1000000)
            block = 0
        elif word == "and" and (block or total):
            continue
        else:
            return None
    return str(total+block) if words and total+block > 0 else None


def context_decision(text, state):
    normalized = normalize(text).strip(" .!?")
    if state.get("active_intent") and normalized in ("iptal", "iptal et", "islemi iptal et", "vazgectim", "cancel", "cancel it", "cancel this", "cancel the operation", "never mind", "stop"):
        return Proposal(decision="cancel", intent_id=state["active_intent"], reason_code="active_flow_cancel")
    if state.get("pending_confirmation"):
        if normalized in ("evet", "onayliyorum", "onayla", "tamam", "devam", "yes", "confirm", "i confirm", "ok", "okay", "proceed"):
            return Proposal(decision="continue", intent_id=state["active_intent"], reason_code="simulation_confirmed")
        if normalized in ("hayir", "onaylamiyorum", "no", "do not confirm", "don't confirm"):
            return Proposal(decision="cancel", intent_id=state["active_intent"], reason_code="confirmation_declined")
        if state.get("active_intent") == "card.limit.change" and "degil" in normalized:
            value = amount(text)
            if value:
                return Proposal(decision="continue", intent_id=state["active_intent"], slots={"new_limit": value}, reason_code="slot_correction")
        if "new_limit" in state.get("slots", {}):
            correction = re.fullmatch(r"(?:no,?\s*)?not\s+.+?,\s*(?:make it\s+)?(.+)", normalized)
            if correction and (value := amount(correction.group(1))):
                return Proposal(decision="continue", intent_id=state["active_intent"], slots={"new_limit": value}, reason_code="slot_correction")
    pending = state.get("pending_slot")
    value = None
    if pending == "new_limit":
        value = amount(text)
    elif pending == "card_last4" and re.fullmatch(r"\d{4}", text.strip()):
        value = text.strip()
    elif pending == "transfer_reference" and re.fullmatch(r"[A-Za-z0-9-]{4,30}", text.strip()) and any(c.isdigit() for c in text):
        value = text.strip()
    if value:
        return Proposal(decision="continue", intent_id=state["active_intent"], slots={pending: value}, reason_code="slot_answer")
    return None


def explicit_workflow_slots(text, intent):
    """Conservative first-turn extraction for the three demo workflows, after intent selection."""
    value = normalize(text)
    slots = {}
    if ("new_limit" in intent.required_slots and "limit" in value and "degil" not in value
            and not re.search(r"\b(?:not|never|no|don['’]t|cannot|can['’]t|won['’]t|shouldn['’]t|mustn['’]t)\b", value)):
        # A target amount must be explicit; an increase by an amount is a delta.
        matches = list(re.finditer(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", value))
        if len(matches) == 1:
            match = matches[0]
            tail = re.sub(r"^\s*(?:tl|lira|try|usd|eur|dollars?|euros?|pounds?)\b", "", value[match.end():]).strip(" .!?")
            target = (bool(re.match(r"(?:olsun\b|yap\b|olarak\b)", tail))
                      or bool(re.match(r"['’]?(?:a|e|ya|ye)\s+(?:cikar|dusur|yuksel|indir|ayarla|artir|yap)", tail))
                      or ("yeni limit" in value[:match.start()] and not tail)
                      or (bool(re.search(r"\blimit\b.*\bto\s*\$?\s*$", value[:match.start()])) and not tail)
                      or (bool(re.search(r"\bnew limit(?: is)?\s*\$?\s*$", value[:match.start()])) and not tail))
            number = amount(match.group())
            if target and number:
                slots["new_limit"] = number
    if "card_last4" in intent.required_slots:
        match = re.search(r"son\s+(?:dort|4)\s+(?:hane(?:si)?|rakam(?:i)?)(?:\s*[:=])?\s+(\d{4})\b", value)
        if match:
            slots["card_last4"] = match.group(1)
        match = re.search(r"(?:last\s+(?:four|4)\s+digits?(?:\s+(?:are|is))?|ending\s+in)\s*[:=]?\s+(\d{4})\b", value)
        if match:
            slots["card_last4"] = match.group(1)
    if "transfer_reference" in intent.required_slots:
        match = re.search(r"(?:referans(?:\s+numara(?:si|m))?|reference(?:\s+(?:number|id))?)(?:\s*[:=])?\s+([a-z0-9-]{4,30})\b", value)
        if match and any(c.isdigit() for c in match.group(1)):
            slots["transfer_reference"] = match.group(1).upper()
    return slots


def baseline_decision(text, candidates, state, semantic=False, rejection_threshold=None):
    if not candidates:
        return Proposal(decision="out_of_scope", reason_code="no_candidates")
    value = normalize(text)
    candidate_ids = {candidate.intent_id for candidate in candidates}
    bank_closure = {"card.temporary_block", "card.cancel"} <= candidate_ids
    closure_request = (("kart" in value and ("kapat" in value or "iptal" in value))
                       or (re.search(r"\bcards?\b", value)
                           and re.search(r"\b(?:close|cancel|block)\b", value)))
    qualifiers = ("gecici", "kalici", "tamamen", "kayip", "kaybet", "calin", "alisveris", "internet",
                  "temporar", "permanent", "lost", "stolen", "online", "internet")
    if bank_closure and closure_request and not any(word in value for word in qualifiers):
        return Proposal(decision="clarify", question="Do you want to temporarily block your card or permanently cancel it?", mentioned_intent_ids=["card.temporary_block", "card.cancel"], reason_code="ambiguous_card_closure")
    if state.get("clarification_options"):
        for option in state["clarification_options"]:
            if option == "card.temporary_block" and option in candidate_ids and ("gecici" in value or "temporar" in value):
                return Proposal(decision="route", intent_id=option, reason_code="clarification_answer")
            if option == "card.cancel" and option in candidate_ids and ("tamamen" in value or "kalici" in value or "permanent" in value):
                return Proposal(decision="route", intent_id=option, reason_code="clarification_answer")
    top = candidates[0]
    if semantic and rejection_threshold is not None and top.score < rejection_threshold:
        return Proposal(decision="out_of_scope", reason_code="calibrated_semantic_rejection")
    if not semantic and (top.lexical_score or 0) < .115:
        return Proposal(decision="out_of_scope", reason_code="uncalibrated_lexical_threshold")
    if len(tokens(text)) < 3 and top.score < (.78 if semantic else .24):
        return Proposal(decision="clarify", question="Which operation would you like help with?", reason_code="insufficient_context")
    return Proposal(decision="handoff" if top.intent_id == "service.human" else "route", intent_id=top.intent_id, reason_code="nearest_intent_baseline")


def apply_decision(proposal, state, catalog, channel="chat"):
    state = copy.deepcopy(state)
    intent = catalog.get(proposal.intent_id)
    result = {"decision": proposal.decision, "intent_id": proposal.intent_id, "intent_name": intent.name if intent else None, "workflow_id": None, "slots": {}, "missing_slots": [], "reason_code": proposal.reason_code, "clarification_options": [], "simulation": True, "simulation_complete": False, "pending_confirmation": False}
    result["dialogue_act"] = {"slot_answer": "slot_answer", "slot_correction": "correction", "active_flow_cancel": "cancel", "simulation_confirmed": "confirmation", "clarification_answer": "clarification_answer"}.get(proposal.reason_code, "new_request")
    if len(proposal.mentioned_intent_ids) > 1:
        result["dialogue_act"] = "multi_intent" if proposal.reason_code != "ambiguous_card_closure" else "ambiguous_request"
    elif proposal.decision == "route" and state.get("active_intent") and state["active_intent"] != proposal.intent_id:
        result["dialogue_act"] = "switch"
    if proposal.decision == "cancel":
        state.update(active_intent=None, slots={}, pending_slot=None, pending_confirmation=False, clarification_options=[], clarifications=0)
        result["message"] = "The active workflow simulation was canceled. You can start another request."
    elif proposal.decision == "clarify":
        state["clarifications"] = state.get("clarifications", 0)+1
        state["clarification_options"] = [i for i in proposal.mentioned_intent_ids if i in catalog]
        if state["clarifications"] > 2:
            result.update(decision="handoff", message="The request is still unclear. Opening the human support handoff preview.", reason_code="clarification_limit")
        else:
            result["message"] = proposal.question or "Which operation would you like to continue with?"
            result["clarification_options"] = [{"intent_id": i, "name": catalog[i].name} for i in state["clarification_options"]]
    elif proposal.decision == "out_of_scope":
        result["message"] = "This request does not match the current intent catalog. Please describe an operation supported by this workspace."
    elif proposal.decision == "handoff":
        result["message"] = "Opening the human support handoff preview. This conversation is a simulation."
    elif proposal.decision in ("route", "continue") and intent:
        if proposal.decision == "continue" and state.get("active_intent") != intent.intent_id:
            raise ValueError("The continuation decision does not match the active workflow.")
        if channel not in intent.channels:
            result.update(decision="handoff", reason_code="channel_unavailable", message=f"{intent.name} is unavailable on this channel. A supported-channel handoff is required.")
            return result, state
        previous = state.get("active_intent")
        if previous != intent.intent_id:
            state.update(slots={}, pending_confirmation=False)
        state.update(active_intent=intent.intent_id, clarification_options=[], clarifications=0)
        for slot, value in proposal.slots.items():
            if slot in intent.required_slots:
                if slot == "new_limit":
                    value = amount(value)
                if slot == "card_last4" and not re.fullmatch(r"\d{4}", value or ""):
                    value = None
                if value:
                    state["slots"][slot] = value[:100]
        missing = [slot for slot in intent.required_slots if slot not in state["slots"]]
        result.update(workflow_id=intent.workflow_id, slots=dict(state["slots"]), missing_slots=missing)
        if any(slot not in {"new_limit", "card_last4", "transfer_reference"} for slot in intent.required_slots):
            state.update(active_intent=None, pending_slot=None, pending_confirmation=False, slots={})
            result["message"] = f"Routed to {intent.name}. This is a workflow preview; required fields belong to the destination workflow."
            return result, state
        state["pending_slot"] = missing[0] if missing else None
        if missing:
            state["pending_confirmation"] = False
            result["message"] = intent.slot_questions.get(missing[0], f"Please provide {missing[0]}.")
        elif intent.required_slots and proposal.reason_code != "simulation_confirmed":
            state["pending_confirmation"] = True
            result["pending_confirmation"] = True
            result["message"] = f"Information for {intent.name} is ready: {', '.join(state['slots'].values())}. Confirm to complete the simulation?"
        elif intent.required_slots:
            state.update(pending_confirmation=False, active_intent=None, pending_slot=None, slots={})
            result.update(simulation_complete=True, message=f"{intent.name} simulation completed. No real transaction was performed.")
        else:
            state["pending_confirmation"] = False
            result["message"] = f"Routed to the {intent.name.lower()} workflow. This screen shows a workflow preview."
    else:
        result.update(decision="error", message="The decision is invalid; no workflow was started.")
    return result, state
