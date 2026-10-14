import json

import httpx
import pytest

from app.config import Settings
from app.contracts import Candidate, Intent
from app.providers import ModelUnavailable
from app.selector import Selector


def select_response(content: str, tmp_path):
    intents = [
        Intent(intent_id="card.lost", name="Kayıp kart", domain="Kartlar",
               description="Kaybolan veya çalınan kartı bildirme.",
               examples=["Kartımı kaybettim."], workflow_id="workflow.card.lost"),
        Intent(intent_id="card.cancel", name="Kart iptali", domain="Kartlar",
               description="Kartı kalıcı olarak iptal etme.",
               examples=["Kartımı iptal et."], workflow_id="workflow.card.cancel"),
    ]
    candidates = [Candidate(intent_id=intent.intent_id, name=intent.name, domain=intent.domain,
                            score=1, score_type="fixture", evidence=intent.examples[0]) for intent in intents]

    requests: list[httpx.Request] = []

    def respond(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_mode="disabled",
                        llm_base_url="http://llm.test/v1", llm_api_key="", openrouter_api_key="")
    selector = Selector(settings, httpx.MockTransport(respond))
    proposal, usage = selector.select("Kartımı kaybettim.", {}, candidates,
                                      {intent.intent_id: intent for intent in intents})
    return proposal, usage, requests[0]


@pytest.mark.parametrize("invalid_value,input_type", [
    ("null", "null"),
    ('"private-customer-value"', "string"),
    ('{"private-customer-value":"sensitive"}', "object"),
    ("123456789", "number"),
    ("123456.789", "number"),
    ("true", "boolean"),
])
def test_invalid_intent_list_reports_json_type_without_response_values(tmp_path, invalid_value, input_type):
    content = json.dumps({"decision": "route", "intent_id": "card.lost",
                          "mentioned_intent_ids": json.loads(invalid_value)})
    with pytest.raises(ModelUnavailable) as caught:
        select_response(content, tmp_path)
    assert caught.value.diagnostics == {
        "service": "llm", "category": "routing_contract",
        "fields": [{"path": "mentioned_intent_ids", "type": "list_type", "input_type": input_type}],
    }


def test_selector_requests_an_explicit_intent_array_from_the_provider(tmp_path):
    proposal, _, request = select_response(
        '{"decision":"route","intent_id":"card.lost","mentioned_intent_ids":[]}', tmp_path)
    response_format = json.loads(request.content)["response_format"]["json_schema"]
    schema = response_format["schema"]
    assert "mentioned_intent_ids" in schema["required"]
    assert schema["properties"]["mentioned_intent_ids"]["type"] == "array"
    assert schema["properties"]["mentioned_intent_ids"]["items"]["enum"] == ["card.lost", "card.cancel"]
    assert response_format["strict"] is False
    assert proposal.decision == "route" and proposal.intent_id == "card.lost"


@pytest.mark.parametrize("reason_code", ["multiple_intents", "ambiguous_intent"])
def test_selector_preserves_valid_clarification_candidates(tmp_path, reason_code):
    content = json.dumps({"decision": "clarify", "intent_id": None,
                          "question": "Kayıp bildirimi mi, kart iptali mi?", "reason_code": reason_code,
                          "mentioned_intent_ids": ["card.lost", "card.cancel"]})
    proposal, _, _ = select_response(content, tmp_path)
    assert proposal.decision == "clarify" and proposal.intent_id is None
    assert proposal.mentioned_intent_ids == ["card.lost", "card.cancel"]
    assert proposal.question == "Kayıp bildirimi mi, kart iptali mi?"


def test_selector_rejects_routing_outside_the_candidate_list(tmp_path):
    content = '{"decision":"route","intent_id":"loan.apply","mentioned_intent_ids":[]}'
    with pytest.raises(ModelUnavailable, match="aday listesinde olmayan"):
        select_response(content, tmp_path)
