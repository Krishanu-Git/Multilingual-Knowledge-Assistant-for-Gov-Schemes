import logging
from .config import LANGUAGES

SUPPORTED={"age","income","state","occupation","beneficiary_category","required_document","district","gender"}
logger=logging.getLogger(__name__)
def assess(record, profile, language="en"):
    rules=record.eligibility_rules or []; conditions=[]; missing=[]; conflicts=[]; failed=False
    logger.debug("Eligibility assessment started: scheme_id=%s rules=%d supplied_profile_fields=%d",record.scheme_id,len(rules),sum(value is not None for value in profile.values()))
    verified=record.verification_status=="verified"
    for n,rule in enumerate(rules):
        field=rule.get("field"); op=rule.get("operator"); expected=rule.get("value")
        if field not in SUPPORTED or not verified or rule.get("verification_status", "verified")!="verified":
            conditions.append({"field":field,"result":"unknown","reason":"Rule is unsupported or not verified","source_url":record.official_source_url}); continue
        actual=profile.get(field)
        if actual is None:
            missing.append(field); conditions.append({"field":field,"rule":expected,"result":"unknown","source_url":record.official_source_url}); continue
        passed=None
        try:
            if op=="min": passed=float(actual)>=float(expected)
            elif op=="max": passed=float(actual)<=float(expected)
            elif op=="equals": passed=str(actual).casefold()==str(expected).casefold()
            elif op=="in": passed=str(actual).casefold() in [str(v).casefold() for v in expected]
            elif op=="contains": passed=str(expected).casefold() in str(actual).casefold()
        except (ValueError,TypeError): pass
        if passed is None: missing.append(field); result="unknown"
        else:
            result="pass" if passed else "fail"; failed |= not passed
        conditions.append({"field":field,"user_value":actual,"rule":expected,"operator":op,"result":result,"source_url":record.official_source_url})
    outcome="potentially_ineligible" if failed else ("potentially_eligible" if rules and verified and not missing and all(c["result"]=="pass" for c in conditions) else "insufficient_information")
    explanations={"en":"Informational assessment only; the responsible authority makes the final decision.","bn":"এটি কেবল তথ্যভিত্তিক মূল্যায়ন; চূড়ান্ত সিদ্ধান্ত সংশ্লিষ্ট কর্তৃপক্ষ নেবে।","hi":"यह केवल सूचनात्मक आकलन है; अंतिम निर्णय संबंधित प्राधिकरण करेगा।"}
    result={"outcome":outcome,"conditions":conditions,"missing_information":sorted(set(missing)),"conflicts":conflicts,"explanation":explanations[language],"official_approval":False}
    logger.debug("Eligibility assessment completed: scheme_id=%s outcome=%s passed=%d failed=%d unknown=%d",record.scheme_id,outcome,sum(c["result"]=="pass" for c in conditions),sum(c["result"]=="fail" for c in conditions),sum(c["result"]=="unknown" for c in conditions))
    return result
