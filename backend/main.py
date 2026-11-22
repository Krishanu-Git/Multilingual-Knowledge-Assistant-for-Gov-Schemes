import logging, json, tempfile, time
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from government_assistant.config import settings, LANGUAGES
from government_assistant.schemas import ChatRequest, RetrievalRequest, EligibilityRequest, FeedbackRequest
from government_assistant.storage import Repository
from government_assistant.service import AssistantService
from government_assistant.eligibility import assess
from government_assistant.speech import SpeechService

logging.basicConfig(level=settings.log_level, format='%(asctime)s %(levelname)s %(name)s %(message)s')
repo=Repository(settings.db_path); assistant=AssistantService(repo); speech=SpeechService()
app=FastAPI(title="Multilingual Government Schemes Assistant",version="0.1.0",description="Local-first, curator-controlled cross-lingual scheme discovery and RAG.")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:8501"],allow_methods=["GET","POST"],allow_headers=["*"])

@app.middleware("http")
async def request_logging(request, call_next):
    started=time.perf_counter()
    logging.getLogger("government_assistant.http").debug("Request started: %s %s",request.method,request.url.path)
    try:
        response=await call_next(request)
    except Exception:
        logging.getLogger("government_assistant.http").exception("Request failed: %s %s",request.method,request.url.path)
        raise
    elapsed=(time.perf_counter()-started)*1000
    logging.getLogger("government_assistant.http").info("%s %s -> %d (%.1f ms)",request.method,request.url.path,response.status_code,elapsed)
    return response

@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/api/v1/status")
def status():
    chunks=repo.chunks()
    logging.getLogger("government_assistant.api").debug("Status requested: schemes=%d chunks=%d",len(repo.schemes()),len(chunks))
    return {"status":"ready","scheme_count":len(repo.schemes()),"document_chunk_count":len(chunks),"llm":{"provider":settings.llm_provider,"model":settings.llm_model,"configured":True},"embeddings":{"enabled":settings.embeddings_enabled,"model":settings.embedding_model},"speech":{"provider":settings.stt_provider,"model":settings.stt_model},"database":"sqlite","paid_api_required":False}

@app.get("/api/v1/languages")
def languages(): return [{"code":code,**value} for code,value in LANGUAGES.items()]

@app.get("/api/v1/schemes")
def list_schemes(q:str|None=None,category:str|None=None,level:str|None=None,state:str|None=None,district:str|None=None):
    results=repo.schemes(q,category,level,state,district)
    logging.getLogger("government_assistant.api").debug("Scheme catalog query returned %d records",len(results))
    return [s.model_dump() for s in results]

@app.get("/api/v1/schemes/{scheme_id}")
def get_scheme(scheme_id:str):
    s=repo.get_scheme(scheme_id)
    if not s: raise HTTPException(404,"Scheme not found")
    logging.getLogger("government_assistant.api").debug("Scheme detail requested: scheme_id=%s",scheme_id)
    return {**s.model_dump(),"documents":[d for d in repo.chunks() if d["scheme_id"]==scheme_id]}

@app.post("/api/v1/schemes/compare")
def compare_schemes(body:dict):
    ids=body.get("scheme_ids", [])
    if not isinstance(ids,list) or not 2 <= len(ids) <= 4 or len(set(ids)) != len(ids):
        raise HTTPException(422,"Select two to four distinct schemes")
    records=[repo.get_scheme(sid) for sid in ids]
    if any(record is None for record in records): raise HTTPException(404,"One or more schemes were not found")
    profile=body.get("profile", {})
    if not isinstance(profile,dict): raise HTTPException(422,"profile must be an object")
    categories=[(record.scheme_category or "").strip().casefold() for record in records]
    same_category=bool(categories[0]) and all(category==categories[0] for category in categories)
    common_domains=None
    for record in records:
        domains=scheme_domains(record.scheme_category)
        common_domains=domains if common_domains is None else common_domains & domains
    related_domain=bool(common_domains)
    relevance_comparable=same_category or related_domain
    compared=[{**record.model_dump(),"relevance_percentage":profile_relevance(record,profile),
               "same_category_comparison":same_category,"related_domain_comparison":relevance_comparable,
               "comparison_basis":"same scheme category" if same_category else ("related scheme domain" if related_domain else None)} for record in records]
    logging.getLogger("government_assistant.compare").debug("Comparison prepared: schemes=%d profile_fields=%d same_category=%s related_domain=%s relevance=%s",len(records),sum(value is not None for value in profile.values()),same_category,related_domain,[item["relevance_percentage"] for item in compared])
    return compared

def scheme_domains(category):
    """Map catalog category labels to broad, comparable scheme domains."""
    value=(category or "").casefold()
    keyword_domains={
        "education":("education","school","student","scholarship","academic"),
        "skills and employment":("skill","employment","youth","job","unemploy","career","training"),
        "agriculture":("agricultur","farmer","farming","crop","fishery","livestock","dairy"),
        "health":("health","medical","hospital","nutrition","wellness"),
        "social protection":("social welfare","social security","empowerment","women","woman","child","disability","pension","senior citizen","widow"),
        "business and finance":("business","enterprise","industry","msme","entrepreneur","finance","financial inclusion","credit","loan"),
        "housing and infrastructure":("housing","rural development","infrastructure","urban development","sanitation","water supply"),
        "energy and environment":("energy","electricity","renewable","environment","climate","forest"),
    }
    return {domain for domain,terms in keyword_domains.items() if any(term in value for term in terms)}

def profile_relevance(scheme, profile):
    """Return a transparent profile match percentage from available evidence."""
    fields=[field for field in ("age","gender","beneficiary_category","income") if profile.get(field) is not None]
    if not fields: return 0
    evidence=" ".join([scheme.eligibility_summary or "",scheme.description or "",
                       " ".join(scheme.target_beneficiaries or [])]).casefold()
    passed=0
    aliases={"SC":("sc", "scheduled caste"),"ST":("st", "scheduled tribe"),
             "OBC":("obc", "other backward class"),"GN":("general", "open category", "all applicants")}
    for field in fields:
        value=profile[field]
        rules=[r for r in (scheme.eligibility_rules or []) if r.get("field")==field]
        matched=False
        if scheme.verification_status=="verified" and rules:
            checks=[]
            for rule in rules:
                expected=rule.get("value"); op=rule.get("operator")
                try:
                    if op=="min": checks.append(float(value)>=float(expected))
                    elif op=="max": checks.append(float(value)<=float(expected))
                    elif op=="equals": checks.append(str(value).casefold()==str(expected).casefold())
                    elif op=="in": checks.append(str(value).casefold() in [str(v).casefold() for v in expected])
                except (TypeError,ValueError): pass
            matched=bool(checks) and all(checks)
        elif field=="age":
            ranges=re.findall(r"(?:age|aged)\D{0,24}(\d{1,3})\s*(?:to|-|–|and)\s*(\d{1,3})",evidence)
            matched=any(int(lo)<=int(value)<=int(hi) for lo,hi in ranges)
        elif field=="gender":
            words={"female":("female","woman","women","girl"),"male":("male","man","men","boy"),"transgender":("transgender",),"other":("gender diverse","other gender")}.get(str(value).casefold(),(str(value).casefold(),))
            matched=any(word in evidence for word in words)
        elif field=="beneficiary_category":
            words=aliases.get(str(value).upper(),(str(value).casefold(),))
            matched=any(re.search(r"\b"+re.escape(word)+r"\b",evidence) for word in words)
        elif field=="income":
            for mention in re.finditer("income",evidence):
                window=evidence[max(0,mention.start()-70):mention.end()+100]
                amount=re.search(r"(\d[\d,]*)",window)
                if not amount: continue
                try: limit=int(amount.group(1).replace(",","")); actual=int(value)
                except (ValueError,TypeError): continue
                if re.search(r"\b(?:below|under|less than|not exceed|up to|upto|maximum)\b",window): matched=actual<=limit
                elif re.search(r"\b(?:above|over|more than|minimum|at least)\b",window): matched=actual>=limit
                if matched: break
        if matched: passed+=1
    return round(100*passed/len(fields))

@app.post("/api/v1/schemes/discover")
def discover_schemes(body:dict):
    profile=body.get("profile", {})
    if not isinstance(profile,dict): raise HTTPException(422,"profile must be an object")
    if body.get("language", "en") not in LANGUAGES: raise HTTPException(422,"Unsupported language")
    state=(profile.get("state") or "").strip()
    scheme_category=(profile.get("scheme_category") or "").strip()
    results=[]
    text_fields=("eligibility_summary", "description", "scheme_name")
    aliases={
        "farmer": ("farmer", "agricultur", "cultivator"), "student": ("student", "scholar"),
        "woman": ("woman", "women", "female", "girl"), "women": ("woman", "women", "female", "girl"),
        "female": ("woman", "women", "female", "girl"), "business": ("business", "enterprise", "entrepreneur", "msme"),
        "unemployed": ("unemploy", "job seeker"), "artisan": ("artisan", "craftsperson"),
    }
    def terms(value):
        normalized=str(value).casefold().strip()
        return aliases.get(normalized, (normalized,))
    def rule_match(scheme, field, actual):
        rules=[rule for rule in (scheme.eligibility_rules or []) if rule.get("field")==field]
        if not rules: return None
        if scheme.verification_status!="verified": return None
        for rule in rules:
            expected=rule.get("value"); operator=rule.get("operator")
            try:
                if operator=="min" and float(actual)<float(expected): return False
                if operator=="max" and float(actual)>float(expected): return False
                if operator=="equals" and str(actual).casefold()!=str(expected).casefold(): return False
                if operator=="in" and str(actual).casefold() not in [str(v).casefold() for v in expected]: return False
                if operator not in {"min","max","equals","in"}: return False
            except (TypeError,ValueError): return False
        return True
    for scheme in repo.schemes():
        # Scope is a hard filter: retain matching state schemes and nationwide
        # central schemes, while excluding records with unknown/mismatched scope.
        scope=(scheme.state or "").strip().casefold()
        nationwide=scope in {"all", "india", "central"} or (scheme.scheme_level or "").casefold()=="central"
        if state and scope!=state.casefold() and not nationwide: continue
        if scheme_category and scheme_category.casefold() not in (scheme.scheme_category or "").casefold(): continue
        result=assess(scheme,profile,body.get("language","en"))
        if result["outcome"] == "potentially_ineligible":
            continue
        evidence=" ".join([getattr(scheme,key) or "" for key in text_fields]+[" ".join(scheme.target_beneficiaries or [])]).casefold()
        relevance=1 if state and scope==state.casefold() else 0
        rejected=False
        # A supplied occupation/category must match the published audience or
        # eligibility text; unknown audiences are not treated as matches.
        for field in ("occupation", "beneficiary_category"):
            actual=profile.get(field)
            if not actual: continue
            structured=rule_match(scheme,field,actual)
            textual=any(term in evidence for term in terms(actual))
            if structured is False or (structured is None and not textual):
                rejected=True; break
            if structured is True or textual: relevance+=2
        if rejected: continue
        for field in ("age", "income", "gender"):
            actual=profile.get(field)
            if actual is None: continue
            structured=rule_match(scheme,field,actual)
            if structured is False:
                rejected=True; break
            if structured is True:
                relevance+=2; continue
            # When no structured rule exists, require an explicit textual
            # indication for numeric criteria; demographic text is a positive
            # match when the scheme names that group.
            aliases_for_field={"gender": terms(actual)}
            if field=="age":
                found=re.search(r"(?:age|aged)\D{0,24}(\d{1,3})\s*(?:to|-|–|and)\s*(\d{1,3})",evidence)
                if found:
                    lo,hi=map(int,found.groups())
                    if not lo<=int(actual)<=hi: rejected=True; break
                    relevance+=2
                elif re.search(r"\b(?:age|aged)\b",evidence):
                    rejected=True; break
            elif field=="income":
                # Only use an explicit cap/floor near an income mention; never
                # guess from unrelated amounts in a scheme description.
                income_match=None
                for mention in re.finditer(r"income", evidence):
                    window=evidence[max(0,mention.start()-70):mention.end()+100]
                    amount=re.search(r"(?:rs\.?|₹|inr)?\s*(\d[\d,]*)\s*(?:/-)?",window)
                    if amount:
                        try:
                            income_limit=int(amount.group(1).replace(",", ""))
                        except ValueError:
                            continue
                        income_match=(window,income_limit); break
                if not income_match:
                    rejected=True; break
                window,limit=income_match
                try:
                    annual_income=int(actual)
                except (TypeError,ValueError):
                    rejected=True; break
                if re.search(r"\b(?:below|under|less than|not exceed|does not exceed|up to|upto|maximum|maximum of)\b",window):
                    if annual_income>limit: rejected=True; break
                elif re.search(r"\b(?:above|over|more than|minimum|at least)\b",window):
                    if annual_income<limit: rejected=True; break
                else:
                    rejected=True; break
                relevance+=2
            else:
                gender=str(actual).casefold()
                female_only=bool(re.search(r"\b(?:only women|women only|female applicants only|only female|exclusively women)\b",evidence))
                male_only=bool(re.search(r"\b(?:only men|men only|male applicants only|only male|exclusively men)\b",evidence))
                if (gender in {"male"} and female_only) or (gender in {"female"} and male_only):
                    rejected=True; break
                if any(term in evidence for term in aliases_for_field["gender"]): relevance+=1
        if rejected or relevance==0: continue
        results.append({**scheme.model_dump(),"eligibility_assessment":result,"relevance_score":relevance})
    results.sort(key=lambda item:(-item["relevance_score"], {"potentially_eligible":0,"insufficient_information":1}.get(item["eligibility_assessment"]["outcome"],2)))
    logging.getLogger("government_assistant.discovery").debug("Personalized discovery completed: profile_fields=%d scheme_category_filter=%s results=%d",sum(value is not None for value in profile.values()),bool(scheme_category),len(results))
    return results

@app.post("/api/v1/chat")
def chat(body:ChatRequest):
    logging.getLogger("government_assistant.chat").debug("Chat request received: language=%s question_characters=%d",body.language,len(body.question))
    result=assistant.chat(body.question,body.language,body.state,body.category)
    logging.getLogger("government_assistant.chat").info("Chat result: evidence=%s citations=%d",result.get("evidence_status"),len(result.get("citations",[])))
    return result

@app.post("/api/v1/chat/stream")
def chat_stream(body:ChatRequest):
    def events():
        for event in assistant.stream_chat(body.question,body.language,body.state,body.category):
            yield "data: "+json.dumps(event,ensure_ascii=False)+"\n\n"
    return StreamingResponse(events(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.post("/api/v1/retrieve")
def retrieval(body:RetrievalRequest):
    results=assistant.retrieve(body.question,body.top_k,body.state,body.category)
    logging.getLogger("government_assistant.api").debug("Retrieval endpoint completed: results=%d",len(results))
    return {"results":results}

@app.post("/api/v1/eligibility/assess")
def eligibility(body:EligibilityRequest):
    s=repo.get_scheme(body.scheme_id)
    if not s: raise HTTPException(404,"Scheme not found")
    result=assess(s,body.profile,body.language)
    logging.getLogger("government_assistant.eligibility").debug("Eligibility assessed: scheme_id=%s outcome=%s supplied_fields=%d",body.scheme_id,result["outcome"],sum(value is not None for value in body.profile.values()))
    return result

@app.post("/api/v1/speech/transcribe")
async def transcribe(audio:UploadFile=File(...),language:str=Form("en")):
    if language not in LANGUAGES: raise HTTPException(422,"language must be en, bn, or hi")
    filename=Path(audio.filename or "audio").name
    if not filename or filename.startswith("."): raise HTTPException(400,"Invalid audio filename")
    if Path(filename).suffix.lower() not in {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac", ".mp4", ".mpeg", ".mpga"}:
        raise HTTPException(415,"Unsupported audio format; use WAV, MP3, M4A, OGG, WEBM or FLAC")
    content=await audio.read(settings.max_audio_mb*1024*1024+1)
    logging.getLogger("government_assistant.speech").debug("Transcription requested: format=%s bytes=%d language=%s",Path(filename).suffix.lower(),len(content),language)
    try: return speech.transcribe(content,filename,language)
    except ValueError as e: raise HTTPException(413 if "exceeds" in str(e) else 400,str(e))
    except RuntimeError as e: raise HTTPException(503,str(e))
    finally: await audio.close()

@app.post("/api/v1/feedback",status_code=201)
def feedback(body:FeedbackRequest):
    repo.save_feedback(body.model_dump()); return {"status":"recorded"}
