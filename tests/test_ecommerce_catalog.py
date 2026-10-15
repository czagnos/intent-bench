"""Behavioral coverage and compatibility of the bundled shopping preset."""
import hashlib
import json
from collections import Counter

from app.calibration import question_hash
from app.catalog_presets import workspace_preset
from app.config import ROOT


def records(filename):
    return json.loads((ROOT / 'data/presets/ecommerce' / filename).read_text())


def test_ecommerce_preset_has_200_bounded_workflows():
    intents = workspace_preset('ecommerce').intents()
    ids = {item.intent_id for item in intents}
    assert len(intents) == len(ids) == 200
    assert len({item.workflow_id for item in intents}) == 200
    for item in intents:
        assert len(item.examples) == 2
        assert item.exclusions and item.selection_rule and item.confusable_with
        assert set(item.confusable_with) <= ids - {item.intent_id}
        assert item.required_slots == list(item.slot_questions)


def test_ecommerce_test_cohort_covers_each_operation():
    cases = records('cases.json')
    ids = {item.intent_id for item in workspace_preset('ecommerce').intents()}
    assert Counter(case['expected_decision'] for case in cases) == {
        'route': 199, 'handoff': 1, 'clarify': 1, 'out_of_scope': 4,
    }
    labels = {case['expected_intent_id'] for case in cases if case['expected_decision'] == 'route'}
    assert labels | {'service.human'} == ids
    assert all(case['split'] == 'test' and case['source'] == 'seed' and case['reviewed'] for case in cases)
    assert all(case['label_origin'].startswith('curated_synthetic') for case in cases)


def test_ecommerce_calibration_is_balanced_and_separate():
    intents = workspace_preset('ecommerce').intents()
    tests = records('cases.json')
    calibration = records('calibration-cases.json')
    assert Counter(case['expected_decision'] for case in calibration) == {'route': 40, 'out_of_scope': 40}
    assert all(case['split'] == 'calibration' for case in calibration)
    assert all(case['expected_intent_id'] in {item.intent_id for item in intents} for case in calibration if case['expected_decision'] == 'route')
    samples = [example for item in intents for example in item.examples] + [case['question'] for case in tests + calibration]
    assert len(samples) == len({question_hash(text) for text in samples})
    assert len(tests + calibration) == len({case['case_id'] for case in tests + calibration})


def test_ecommerce_original_workflow_ids_and_case_text_are_compatible():
    original_ids = set((
        'ecommerce.product.search ecommerce.product.compare ecommerce.product.details '
        'ecommerce.product.availability ecommerce.product.restock ecommerce.product.sizing '
        'ecommerce.product.authenticity ecommerce.product.reviews ecommerce.product.price ecommerce.cart.add '
        'ecommerce.cart.quantity ecommerce.cart.remove ecommerce.cart.saved ecommerce.checkout.help '
        'ecommerce.checkout.guest ecommerce.checkout.address ecommerce.checkout.place '
        'ecommerce.payment.methods ecommerce.payment.failed ecommerce.payment.pending '
        'ecommerce.payment.duplicate ecommerce.payment.invoice ecommerce.payment.giftcard '
        'ecommerce.promotion.eligibility ecommerce.promotion.apply ecommerce.order.confirmation '
        'ecommerce.order.status ecommerce.order.change ecommerce.order.address ecommerce.order.cancel '
        'ecommerce.order.cancel_item ecommerce.order.preorder ecommerce.order.backorder '
        'ecommerce.order.repeat ecommerce.delivery.options ecommerce.delivery.date ecommerce.delivery.track '
        'ecommerce.delivery.delay ecommerce.delivery.failed ecommerce.delivery.instructions '
        'ecommerce.delivery.delivered_missing ecommerce.delivery.lost ecommerce.delivery.partial '
        'ecommerce.delivery.pickup ecommerce.delivery.pickup_extend ecommerce.delivery.international '
        'ecommerce.return.policy ecommerce.return.request ecommerce.return.label ecommerce.return.pickup '
        'ecommerce.return.status ecommerce.return.cancel ecommerce.exchange.request ecommerce.exchange.status '
        'ecommerce.refund.status ecommerce.refund.amount ecommerce.refund.missing ecommerce.issue.damaged '
        'ecommerce.issue.defective ecommerce.issue.wrong_item ecommerce.issue.missing_item '
        'ecommerce.issue.empty_package ecommerce.warranty.coverage ecommerce.warranty.claim '
        'ecommerce.warranty.repair ecommerce.warranty.parts ecommerce.account.create ecommerce.account.login '
        'ecommerce.account.profile ecommerce.account.security ecommerce.account.delete '
        'ecommerce.privacy.request ecommerce.subscription.create ecommerce.subscription.change '
        'ecommerce.subscription.cancel ecommerce.loyalty.balance ecommerce.loyalty.redeem '
        'ecommerce.review.submit ecommerce.seller.contact ecommerce.seller.dispute ecommerce.seller.onboard '
        'ecommerce.seller.payout ecommerce.support.complaint service.human '
    ).split())
    pairs = sorted((item['intent_id'], item['workflow_id']) for item in records('catalog.json') if item['intent_id'] in original_ids)
    assert hashlib.sha256(json.dumps(pairs).encode()).hexdigest() == 'c21a6e191dae9210846faf37b076c7bb01836efa452049c7662cda264cad1e6f'
    for filename, digest in (
        ('cases.json', 'cceaaca946d04e911f708339a6e31f15cf2f194e3c8ad9644673a08cb9ab27f1'),
        ('calibration-cases.json', '68ef2a83c4e7838dea097bb2237b144b7896c3c7c36f7d0abf1f491a341fe098'),
    ):
        pairs = sorted((case['case_id'], case['question'], case['expected_decision'], case['expected_intent_id'])
                       for case in records(filename) if '-v1-' in case['case_id'])
        assert hashlib.sha256(json.dumps(pairs).encode()).hexdigest() == digest
