"""Export myScheme scheme records for three states and index them locally.

Uses the public JSON endpoints called by myScheme's own web client. The site
owner's written authorization is required before running this collector.
Responses are cached under data/raw/myscheme so interrupted runs can resume.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from government_assistant.config import settings
from government_assistant.ingestion import ingest_document
from government_assistant.schemas import SchemeRecord
from government_assistant.storage import Repository

logger=logging.getLogger("gsa.collector")

SITE = "https://www.myscheme.gov.in"
API = f"{SITE}/api/apisetu"
STATES = ("West Bengal", "Bihar", "Jharkhand")
USER_AGENT = "GovernmentSchemesAssistant/0.1 (authorized myScheme data export)"


def request_json(url, timeout=45, retries=5):
    for attempt in range(retries):
        try:
            logger.debug("Fetching source endpoint: path=%s attempt=%d/%d",url.split("?",1)[0].removeprefix(SITE),attempt+1,retries)
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            logger.warning("Source endpoint returned HTTP %d: attempt=%d/%d",exc.code,attempt+1,retries)
            if exc.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise
            time.sleep(min(30, 2 ** attempt))
        except (URLError, TimeoutError):
            logger.exception("Source endpoint request failed: attempt=%d/%d",attempt+1,retries)
            if attempt == retries - 1:
                raise
            time.sleep(min(30, 2 ** attempt))


def list_schemes(state=None, page_size=100):
    filters = [{"identifier": "level", "value": "Central"}] if state is None else [
        {"identifier": "beneficiaryState", "value": state},
        {"identifier": "level", "value": "State"},
    ]
    rows, offset = [], 0
    while True:
        query = urlencode({"lang": "en", "q": json.dumps(filters, separators=(",", ":")),
                           "keyword": "", "sort": "multiple_sort" if state else "", "from": offset, "size": page_size})
        data = request_json(f"{API}/search/schemes?{query}").get("data", {}).get("hits", {})
        items = data.get("items", [])
        rows.extend(x.get("fields", {}) for x in items)
        total = int(data.get("page", {}).get("total", 0))
        if not items or offset + len(items) >= total:
            break
        offset += len(items)
    return rows


def rich_text(value):
    """Flatten myScheme's nested rich-text blocks, retaining link destinations."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part for part in (rich_text(x) for x in value) if part.strip())
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            text = value["text"]
            link = value.get("link")
            return f"{text} ({link})" if link else text
        text = rich_text(value.get("children", []))
        return f"{text} ({value['link']})" if value.get("link") and text else text
    return str(value)


def category_labels(value):
    if not value:
        return []
    if not isinstance(value, list):
        value = [value]
    return [x.get("label", str(x)) if isinstance(x, dict) else str(x) for x in value]


def web_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip().rstrip(".,;)")
    if value.startswith("www."):
        value = "https://" + value
    from urllib.parse import urlparse
    parsed = urlparse(value)
    return value if parsed.scheme in ("http", "https") and parsed.hostname and not any(ch.isspace() for ch in value) else None


def listing_only(slug, listing):
    state = listing.get("beneficiaryState") or []
    record = SchemeRecord(
        scheme_id=f"myscheme-{slug}", scheme_name=listing.get("schemeName") or slug,
        description=listing.get("briefDescription"), scheme_category=", ".join(category_labels(listing.get("schemeCategory"))) or None,
        scheme_level=listing.get("level"), state=state[0] if state else None,
        target_beneficiaries=listing.get("tags") or None, responsible_department=listing.get("nodalDepartmentName"),
        official_source_url=f"{SITE}/schemes/{slug}", source_title=listing.get("schemeName") or slug,
        source_type="myScheme listing record", source_language="en",
        source_last_verified_date=None,
        verification_status="unverified", verification_evidence="Listing summary collected from myScheme; detailed fields were not available in this export.",
        ingestion_status="pending",
    )
    body = f"Scheme: {record.scheme_name}\nSource: {record.official_source_url}\nDescription: {record.description or ''}\nCategory: {record.scheme_category or ''}\nLevel: {record.scheme_level or ''}\nState: {record.state or ''}\nTags: {', '.join(record.target_beneficiaries or [])}"
    return record, body, []


def parse_detail(slug, listing, raw):
    data = raw.get("data", {})
    lang = data.get("en") or {}
    basic = lang.get("basicDetails") or {}
    content = lang.get("schemeContent") or {}
    eligibility = lang.get("eligibilityCriteria") or {}
    docs_data = (raw.get("documents", {}).get("data") or {})
    faqs_data = (raw.get("faqs", {}).get("data") or {})
    docs = (docs_data.get("en") or {}).get("documents_required", [])
    faqs = (faqs_data.get("en") or {}).get("faqs", [])
    benefits_value = content.get("benefits") or []
    benefits = [rich_text(x).strip() for x in benefits_value]
    benefits = [x for x in benefits if x]
    if not benefits and content.get("benefitTypes"):
        benefits = [content["benefitTypes"].get("label", "")]
    description = content.get("detailedDescription_md") or content.get("briefDescription") or listing.get("briefDescription")
    eligibility_text = eligibility.get("eligibilityDescription_md") or rich_text(eligibility.get("eligibilityDescription"))
    process_blocks = []
    process_urls = []
    for item in lang.get("applicationProcess", []) or []:
        if item.get("url"):
            process_urls.append(item["url"])
        for block in item.get("process", []) or []:
            text = rich_text(block).strip()
            if text:
                process_blocks.append(text)
    required_docs = rich_text(docs).strip()
    doc_list = [x.strip(" •\t") for x in re.split(r"\n+", required_docs) if x.strip(" •\t")]
    state_obj = basic.get("state") or {}
    level_obj = basic.get("level") or {}
    listing_states = listing.get("beneficiaryState") or []
    if listing.get("level") == "Central" and any(str(value).casefold() == "all" for value in listing_states):
        listing_state = "All"
    else:
        listing_state = listing_states[0] if listing_states else None
    detail_level = level_obj.get("label") if isinstance(level_obj, dict) else level_obj
    applicable_state = listing.get("_collection_scope") or (
        (state_obj.get("label") if isinstance(state_obj, dict) else state_obj) or listing_state
    )
    refs = content.get("references", []) or []
    source_page = f"{SITE}/schemes/{slug}"
    source_lines = [f"Scheme: {basic.get('schemeName') or listing.get('schemeName', slug)}",
                    f"Source: {source_page}", f"Brief description: {content.get('briefDescription') or listing.get('briefDescription') or ''}",
                    f"Detailed description: {rich_text(content.get('detailedDescription_md') or content.get('detailedDescription'))}",
                    f"Benefits: {rich_text(benefits_value)}", f"Eligibility: {eligibility_text}",
                    f"Application process: {' '.join(process_blocks)}", f"Application URLs: {' '.join(process_urls)}",
                    f"Documents required: {required_docs}"]
    if refs:
        source_lines.append("References:")
        source_lines.extend(f"- {ref.get('title', 'Source')}: {ref.get('url', '')}" for ref in refs)
    if faqs:
        source_lines.append("Frequently asked questions:")
        source_lines.extend(f"Q: {faq.get('question', '')}\nA: {faq.get('answer_md') or rich_text(faq.get('answer'))}" for faq in faqs)

    record = SchemeRecord(
        scheme_id=f"myscheme-{slug}",
        scheme_name=basic.get("schemeName") or listing.get("schemeName") or slug,
        scheme_name_original=basic.get("schemeName"),
        description=description,
        benefits=benefits or None,
        eligibility_summary=eligibility_text or None,
        required_documents=doc_list or None,
        application_process="\n".join(process_blocks) or None,
        application_url=next((url for url in (web_url(x) for x in process_urls) if url), None),
        scheme_category=", ".join(category_labels(basic.get("schemeCategory") or listing.get("schemeCategory"))) or None,
        scheme_level=detail_level or listing.get("level"),
        state=applicable_state,
        target_beneficiaries=category_labels(basic.get("targetBeneficiaries")) or listing.get("tags") or None,
        responsible_department=(basic.get("nodalDepartmentName") or {}).get("label") if isinstance(basic.get("nodalDepartmentName"), dict) else basic.get("nodalDepartmentName"),
        official_source_url=source_page,
        source_title=basic.get("schemeName") or listing.get("schemeName"),
        source_type="myScheme public scheme record",
        source_language="en",
        source_last_verified_date=None,
        source_version=basic.get("schemeCloseDate"),
        verification_status="unverified",
        verification_evidence="Imported from myScheme with written authorization; details remain unverified against the implementing department.",
        ingestion_status="pending",
    )
    return record, "\n\n".join(source_lines), refs


def fetch_full_record(slug, listing, cache_dir):
    cache = cache_dir / f"{slug}.json"
    if cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            return raw
        except (json.JSONDecodeError, OSError):
            pass
    detail_url = f"{API}/schemes?slug={quote(slug)}&lang=en"
    detail = request_json(detail_url)
    data = detail.get("data") or {}
    scheme_id = data.get("_id")
    if not scheme_id:
        raise ValueError(f"No detail record returned for slug {slug}")
    raw = {"data": data, "detail_url": detail_url}
    for key, endpoint in (("documents", f"{API}/schemes/{scheme_id}/documents?lang=en"),
                          ("faqs", f"{API}/schemes/{scheme_id}/faqs?lang=en")):
        try:
            raw[key] = request_json(endpoint)
        except Exception as exc:
            raw[key] = {"fetch_error": str(exc)}
    cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return raw


def main():
    parser = argparse.ArgumentParser(description="Gather myScheme central and three-state scheme data, write JSON, and index it locally.")
    parser.add_argument("--states", nargs=3, default=list(STATES), metavar=("STATE1", "STATE2", "STATE3"))
    parser.add_argument("--workers", type=int, default=5, help="Concurrent scheme detail requests (default: 5).")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached source responses and download again.")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "curated" / "myscheme_schemes.json")
    args = parser.parse_args()
    logger.info("Scheme collection started: states=%d workers=%d refresh=%s",len(args.states),args.workers,args.refresh)
    if args.workers < 1 or args.workers > 8:
        parser.error("--workers must be between 1 and 8")
    cache_dir = ROOT / "data" / "raw" / "myscheme"
    text_dir = ROOT / "data" / "processed" / "myscheme"
    if args.refresh and cache_dir.exists():
        for path in cache_dir.glob("*.json"):
            path.unlink()
    cache_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    listings = []
    print("Fetching central schemes…", flush=True)
    targeted_states = {state.casefold() for state in args.states}
    central_rows = list_schemes()
    logger.debug("Central listings received: count=%d",len(central_rows))
    for row in central_rows:
        beneficiaries = [str(value).casefold() for value in (row.get("beneficiaryState") or [])]
        if not beneficiaries or "all" in beneficiaries or targeted_states.intersection(beneficiaries):
            row["_collection_scope"] = "All" if not beneficiaries or "all" in beneficiaries else next(
                state for state in args.states if state.casefold() in beneficiaries
            )
            listings.append(row)
    for state in args.states:
        print(f"Fetching {state} schemes…", flush=True)
        for row in list_schemes(state=state):
            row["_collection_scope"] = state
            listings.append(row)
    by_slug = {}
    for row in listings:
        slug = row.get("slug")
        if slug and (slug not in by_slug or by_slug[slug].get("_collection_scope") != "All"):
            by_slug[slug] = row
    print(f"Found {len(by_slug)} unique schemes. Fetching details…", flush=True)
    logger.info("Scheme detail fetch started: unique_schemes=%d",len(by_slug))

    results, errors = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(fetch_full_record, slug, row, cache_dir): (slug, row) for slug, row in by_slug.items()}
        for completed, future in enumerate(as_completed(jobs), 1):
            slug, listing = jobs[future]
            try:
                raw = future.result()
                record, text, refs = parse_detail(slug, listing, raw)
            except Exception as exc:
                errors.append({"slug": slug, "error": str(exc)})
                record, text, refs = listing_only(slug, listing)
            results.append((record, text, refs, slug))
            if completed % 50 == 0 or completed == len(jobs):
                print(f"Fetched {completed}/{len(jobs)} details ({len(errors)} errors)", flush=True)
                logger.debug("Collection progress: completed=%d total=%d errors=%d",completed,len(jobs),len(errors))

    results.sort(key=lambda row: row[0].scheme_name.casefold())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    repo = Repository(settings.db_path)
    keep_ids = {record.scheme_id for record, _, _, _ in results}
    keep_slugs = {slug for _, _, _, slug in results}
    for old_text in text_dir.glob("*.txt"):
        if old_text.stem not in keep_slugs:
            old_text.unlink()
    with repo.connect() as db:
        old_ids = [row[0] for row in db.execute("SELECT scheme_id FROM schemes WHERE scheme_id LIKE 'myscheme-%'") if row[0] not in keep_ids]
        for stale_id in old_ids:
            db.execute("DELETE FROM chunks WHERE scheme_id=?", (stale_id,))
            db.execute("DELETE FROM documents WHERE scheme_id=?", (stale_id,))
            db.execute("DELETE FROM schemes WHERE scheme_id=?", (stale_id,))
    for record, text, refs, slug in results:
        repo.upsert_scheme(record)
        source_file = text_dir / f"{slug}.txt"
        source_file.write_text(text, encoding="utf-8")
        ingest_document(repo, record.scheme_id, source_file, record.source_title, record.official_source_url,
                        settings.chunk_size, settings.chunk_overlap)
        record.ingestion_status = "ingested"
    args.output.write_text(json.dumps([record.model_dump(mode="json") for record, _, _, _ in results], ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"collected_at_utc": datetime.now(timezone.utc).isoformat(),
              "source": "myScheme public scheme listing/detail endpoints",
              "schemes_found": len(by_slug), "schemes_exported": len(results), "detail_errors": errors,
              "full_detail_records": len(results) - len(errors), "listing_only_records": len(errors),
              "states": list(args.states), "central_schemes_included": True, "age_filter": None,
              "json_file": str(args.output), "indexed_in_database": len(results)}
    report_path = args.output.with_name("myscheme_collection_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    logger.info("Scheme collection completed: exported=%d detail_errors=%d indexed=%d",len(results),len(errors),len(results))


if __name__ == "__main__":
    main()
