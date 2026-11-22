import logging, time
from .config import settings, LANGUAGES
from .generation import LocalLLM, fallback_answer, valid_citations
from .retrieval import retrieve

logger=logging.getLogger(__name__)

class AssistantService:
    def __init__(self, repo): self.repo=repo; self.llm=LocalLLM()
    def _evidence(self, question, top_k, state=None, category=None):
        docs=self.repo.chunks(); schemes={s.scheme_id:s for s in self.repo.schemes()}
        logger.debug("Building retrieval context: chunks=%d schemes=%d top_k=%s",len(docs),len(schemes),top_k or settings.top_k)
        for d in docs:
            s=schemes.get(d["scheme_id"])
            if s: d.update(scheme_name=s.scheme_name,scheme_category=s.scheme_category,state=s.state,scheme_level=s.scheme_level)
        return retrieve(question,docs,top_k or settings.top_k,settings.embedding_model,settings.embeddings_enabled,{"state":state,"category":category}), schemes
    def retrieve(self, question, top_k=None, state=None, category=None):
        hits, schemes=self._evidence(question,top_k,state,category)
        return [self._public_hit(h,schemes) for h in hits]
    @staticmethod
    def _public_hit(h, schemes):
        return {k:v for k,v in {**h,"scheme_name":(schemes.get(h["scheme_id"]).scheme_name if schemes.get(h["scheme_id"]) else None)}.items() if k!="content_hash"}
    @staticmethod
    def _scheme_name_prefix(hits, schemes, language):
        names=[]
        for hit in hits:
            record=schemes.get(hit["scheme_id"])
            name=record.scheme_name if record else hit.get("scheme_name")
            if name and name not in names: names.append(name)
        if not names: return ""
        label={"en":"Relevant schemes", "bn":"প্রাসঙ্গিক প্রকল্প", "hi":"प्रासंगिक योजनाएँ"}.get(language,"Relevant schemes")
        return f"**{label}:** " + ", ".join(names) + "\n\n"
    def chat(self, question, language="en", state=None, category=None):
        start=time.perf_counter(); hits, schemes=self._evidence(question,None,state,category)
        logger.debug("Chat evidence retrieved: hits=%d top_score=%s language=%s",len(hits),hits[0].get("retrieval_score") if hits else None,language)
        citations=[]; sources=[]
        if not hits or hits[0].get("retrieval_score",0)<settings.min_score:
            logger.debug("Chat returning abstention: minimum_score=%.5f",settings.min_score)
            return {"answer":LANGUAGES[language]["abstain"],"language":language,"citations":[],"retrieved_sources":[],"evidence_status":"insufficient","follow_up_questions":[],"eligibility_assessment":None,"warnings":[],"processing_time_ms":round((time.perf_counter()-start)*1000)}
        for i,h in enumerate(hits,1):
            s=schemes.get(h["scheme_id"]); citation={"citation_id":i,"scheme_id":h["scheme_id"],"scheme_name":s.scheme_name if s else h.get("scheme_name"),"document_id":h["document_id"],"chunk_id":h["chunk_id"],"source_title":h["source_title"],"source_url":h.get("source_url"),"page_number":h.get("page_number"),"section_title":h.get("section_title"),"verification_status":h["verification_status"],"source_last_verified_date":s.source_last_verified_date if s else None,"excerpt":h["content"]}
            citations.append(citation); sources.append({**citation,"retrieval_score":h["retrieval_score"],"retrieval_mode":h["retrieval_mode"]})
        answer,provider=self.llm.generate(question,language,hits)
        logger.debug("Chat generation finished: provider=%s answer_present=%s",provider,bool(answer))
        if not answer: answer=fallback_answer(hits,language)
        answer=self._scheme_name_prefix(hits,schemes,language)+answer
        used=valid_citations(answer,hits)
        if provider=="ollama" and not used: answer += "\n\nSources: "+", ".join(f"[{i}]" for i in range(1,len(hits)+1))
        warnings=[]
        if any(c["verification_status"]!="verified" for c in citations): warnings.append("Some evidence is not marked verified; check source status before acting.")
        if any(c["verification_status"] in ("outdated","superseded") for c in citations): warnings.append("Some retrieved evidence may be outdated or superseded.")
        if provider=="unavailable": warnings.append(f"Local LLM {settings.llm_model} is unavailable. Showing source excerpts; install/start Ollama and pull the configured model for generated answers.")
        result={"answer":answer,"language":language,"citations":citations,"retrieved_sources":sources,"evidence_status":"available","follow_up_questions":[],"eligibility_assessment":None,"warnings":warnings,"generation_provider":provider,"processing_time_ms":round((time.perf_counter()-start)*1000)}
        logger.debug("Chat response assembled: citations=%d sources=%d elapsed_ms=%d",len(citations),len(sources),result["processing_time_ms"])
        return result

    def stream_chat(self, question, language="en", state=None, category=None):
        """Yield progress, token, and final-result events for a chat response."""
        start=time.perf_counter()
        yield {"type":"status","message":"Searching the local scheme catalog and ranking relevant passages..."}
        hits, schemes=self._evidence(question,None,state,category)
        logger.debug("Streaming chat evidence retrieved: hits=%d language=%s",len(hits),language)
        if not hits or hits[0].get("retrieval_score",0)<settings.min_score:
            result={"answer":LANGUAGES[language]["abstain"],"language":language,"citations":[],"retrieved_sources":[],"evidence_status":"insufficient","follow_up_questions":[],"eligibility_assessment":None,"warnings":[],"processing_time_ms":round((time.perf_counter()-start)*1000)}
            yield {"type":"status","message":"No sufficiently relevant source was found."}
            yield {"type":"token","text":result["answer"]}
            yield {"type":"done","result":result}
            return

        citations=[]; sources=[]
        for i,h in enumerate(hits,1):
            s=schemes.get(h["scheme_id"])
            citation={"citation_id":i,"scheme_id":h["scheme_id"],"scheme_name":s.scheme_name if s else h.get("scheme_name"),"document_id":h["document_id"],"chunk_id":h["chunk_id"],"source_title":h["source_title"],"source_url":h.get("source_url"),"page_number":h.get("page_number"),"section_title":h.get("section_title"),"verification_status":h["verification_status"],"source_last_verified_date":s.source_last_verified_date if s else None,"excerpt":h["content"]}
            citations.append(citation); sources.append({**citation,"retrieval_score":h["retrieval_score"],"retrieval_mode":h["retrieval_mode"]})

        mode=hits[0].get("retrieval_mode","bm25")
        method="hybrid lexical + semantic search" if mode=="hybrid" else "BM25 keyword search"
        yield {"type":"status","message":f"Ranked {len(hits)} passages using {method}; reviewing their source status..."}
        yield {"type":"retrieved_sources","items":[{**source,"excerpt":source["excerpt"][:1200]} for source in sources]}
        prefix=self._scheme_name_prefix(hits,schemes,language)
        if prefix: yield {"type":"token","text":prefix}
        yield {"type":"status","message":f"Preparing a grounded prompt from {len(hits)} retrieved passages..."}
        fragments=[]; provider="disabled"; interrupted=False
        if settings.llm_provider=="ollama":
            provider="ollama"
            yield {"type":"status","message":f"Streaming the answer from local Ollama ({settings.llm_model})..."}
            try:
                for fragment in self.llm.stream(question,language,hits):
                    fragments.append(fragment)
                    yield {"type":"token","text":fragment}
            except Exception:
                logger.exception("Streaming Ollama generation failed")
                provider="unavailable"; interrupted=bool(fragments)
        answer="".join(fragments)
        if not answer:
            answer=fallback_answer(hits,language)
            yield {"type":"token","text":answer}
        answer=prefix+answer
        used=valid_citations(answer,hits)
        if provider=="ollama" and not used:
            refs="\n\nSources: "+", ".join(f"[{i}]" for i in range(1,len(hits)+1))
            answer+=refs; yield {"type":"token","text":refs}
        warnings=[]
        if any(c["verification_status"]!="verified" for c in citations): warnings.append("Some evidence is not marked verified; check source status before acting.")
        if any(c["verification_status"] in ("outdated","superseded") for c in citations): warnings.append("Some retrieved evidence may be outdated or superseded.")
        if provider=="unavailable" and not interrupted: warnings.append(f"Local LLM {settings.llm_model} is unavailable. Showing source excerpts; install/start Ollama and pull the configured model for generated answers.")
        if interrupted: warnings.append("Streaming generation stopped before completion. The visible answer may be incomplete.")
        result={"answer":answer,"language":language,"citations":citations,"retrieved_sources":sources,"evidence_status":"available","follow_up_questions":[],"eligibility_assessment":None,"warnings":warnings,"generation_provider":provider,"processing_time_ms":round((time.perf_counter()-start)*1000)}
        logger.debug("Streaming chat completed: provider=%s citations=%d elapsed_ms=%d interrupted=%s",provider,len(citations),result["processing_time_ms"],interrupted)
        yield {"type":"done","result":result}
