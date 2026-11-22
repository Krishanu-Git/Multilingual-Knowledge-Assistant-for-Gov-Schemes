from government_assistant.eligibility import assess
from government_assistant.schemas import SchemeRecord

def test_unknown_and_verified_assessment():
    s=SchemeRecord(scheme_id="s",scheme_name="S",verification_status="verified",eligibility_rules=[{"field":"age","operator":"min","value":18}])
    assert assess(s,{},"en")["outcome"]=="insufficient_information"
    assert assess(s,{"age":20},"en")["outcome"]=="potentially_eligible"
    assert assess(s,{"age":16},"en")["outcome"]=="potentially_ineligible"

def test_unverified_rules_never_claim_eligible():
    s=SchemeRecord(scheme_id="s",scheme_name="S",eligibility_rules=[{"field":"age","operator":"min","value":18}])
    assert assess(s,{"age":40},"en")["outcome"]=="insufficient_information"
