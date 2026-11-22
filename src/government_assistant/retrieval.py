import logging, math, re
from collections import Counter
from functools import lru_cache

TOKEN=re.compile(r"[\w\u0980-\u09ff\u0900-\u097f]+",re.UNICODE)
logger=logging.getLogger(__name__)
def tokens(s): return [x.casefold() for x in TOKEN.findall(s or "")]

# Small domain vocabulary for lexical retrieval when the curated source text is
# English but the user asks in Hindi or Bengali. Keep the original query terms
# too, so native-language documents continue to match normally.
_QUERY_TRANSLATIONS = {
    "पश्चिम बंगाल": "west bengal", "পশ্চিম बंगाल": "west bengal",
    "পশ্চিমবঙ্গ": "west bengal", "পশ্চিমবঙ্গে": "west bengal",
    "শিক্ষা": "education", "শিক্ষার": "education", "शिक्षा": "education", "पढ़ाई": "education",
    "স্কুল": "school education", "বিদ্যালয়": "school education", "विद्यालय": "school education",
    "छात्र": "student", "छात्रों": "students", "विद्यार्थी": "students",
    "শিক্ষার্থী": "students", "ছাত্র": "students",
    "स्वास्थ्य": "health", "স্বাস্থ্য": "health", "किसान": "farmer farmers",
    "কৃষক": "farmer farmers", "महिला": "women woman", "महिलाओं": "women",
    "নারী": "women woman", "মহিলা": "women woman", "रोजगार": "employment",
    "কর্মসংস্থান": "employment", "দিব্যांग": "disability disabled",
    "दिव्यांग": "disability disabled", "বেকার": "unemployed employment",
    "योजना": "scheme", "योजनाएं": "schemes scheme", "योजनाओं": "schemes scheme",
    "স্কিম": "scheme", "প্রকল্প": "scheme", "প্রকল্পগুলি": "schemes scheme",
}

def query_terms(question):
    expanded=list(tokens(question))
    folded=(question or "").casefold()
    for phrase,english in sorted(_QUERY_TRANSLATIONS.items(),key=lambda item:len(item[0]),reverse=True):
        if phrase.casefold() in folded:
            expanded.extend(tokens(english))
    return expanded

@lru_cache(maxsize=2)
def _load_encoder(model_id):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_id)

def dense_scores(question, docs, model_id):
    logger.debug("Loading multilingual encoder: model=%s documents=%d",model_id,len(docs))
    model=_load_encoder(model_id)
    q=model.encode(["query: "+question],normalize_embeddings=True)[0]
    vectors=model.encode(["passage: "+d["content"] for d in docs],normalize_embeddings=True,batch_size=16)
    return [float(v @ q) for v in vectors]

def retrieve(question, docs, top_k=5, model_id=None, dense_enabled=False, filters=None):
    filters=filters or {}; candidates=[]
    logger.debug("Retrieval started: documents=%d top_k=%d dense_enabled=%s state_filter=%s category_filter=%s",len(docs),top_k,dense_enabled,bool(filters.get("state")),bool(filters.get("category")))
    for d in docs:
        if filters.get("category") or filters.get("state"):
            # Scheme metadata is looked up by caller; filter carried into evidence where available.
            if filters.get("category") and filters.get("category").casefold() not in (d.get("scheme_category") or "").casefold(): continue
            if filters.get("state") and filters.get("state").casefold() not in (d.get("state") or "").casefold() and (d.get("scheme_level") or "").casefold()!="central": continue
        candidates.append(d)
    if not candidates:
        logger.debug("Retrieval stopped: no documents matched metadata filters")
        return []
    q=query_terms(question); dfs=Counter()
    doc_tokens=[tokens(" ".join(str(d.get(k) or "") for k in
                                ("content","scheme_name","scheme_category","state","scheme_level")))
                for d in candidates]
    for terms in doc_tokens: dfs.update(set(terms))
    avg=sum(map(len,doc_tokens))/len(doc_tokens) or 1
    lexical=[]
    for terms in doc_tokens:
        tf=Counter(terms); score=0.0
        for term in set(q):
            if term not in tf: continue
            idf=math.log(1+(len(candidates)-dfs[term]+.5)/(dfs[term]+.5)); f=tf[term]
            score += idf*(f*2.2)/(f+1.2*(.25+.75*len(terms)/avg))
        lexical.append(score)
    dense=[0.0]*len(candidates)
    dense_status="disabled"
    if dense_enabled and model_id:
        try: dense=dense_scores(question,candidates,model_id); dense_status="enabled"
        except Exception:
            dense_status="unavailable"
            logger.exception("Dense retrieval failed; continuing with BM25")
    ranks=[]
    def rank(scores): return {i:r+1 for r,i in enumerate(sorted(range(len(scores)),key=lambda j:scores[j],reverse=True))}
    br=rank(lexical); dr=rank(dense) if dense_status=="enabled" else {}
    maxlex=max(lexical) or 1
    for i,d in enumerate(candidates):
        fusion=(1/(60+br[i]))+(1/(60+dr[i]) if dr else 0)
        normlex=lexical[i]/maxlex
        score=(0.55*normlex+0.45*max(0,dense[i]) if dr else normlex)
        ranks.append((fusion+score*.001,i,score))
    out=[]
    for _,i,score in sorted(ranks,reverse=True)[:top_k]:
        d=candidates[i].copy(); d["retrieval_score"]=round(score,5); d["retrieval_mode"]="hybrid" if dense_status=="enabled" else "bm25"; out.append(d)
    logger.debug("Retrieval completed: candidates=%d returned=%d mode=%s top_score=%s",len(candidates),len(out),"hybrid" if dense_status=="enabled" else "bm25",out[0]["retrieval_score"] if out else None)
    return out
