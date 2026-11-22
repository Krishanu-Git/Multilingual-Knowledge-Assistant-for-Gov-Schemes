import logging
import json
import html
import os
import re
import sys
import time

import streamlit as st
import requests
import streamlit.components.v1 as components

from services.api_client import BASE, get, post, stream_chat


logging.basicConfig(
    level=os.getenv("GSA_LOG_LEVEL", "DEBUG").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logging.getLogger().setLevel(os.getenv("GSA_LOG_LEVEL", "DEBUG").upper())
logger = logging.getLogger("gsa.frontend")
logger.setLevel(os.getenv("GSA_LOG_LEVEL", "DEBUG").upper())


def render_read_aloud(text, language, ready=False):
    """Render a browser-native speech control for one scheme summary."""
    locale = {"en": "en-IN", "bn": "bn-IN", "hi": "hi-IN"}.get(language, "en-IN")
    # Escape characters that could terminate the script element; text is inserted
    # into the utterance as data and never interpreted as markup.
    safe_text = json.dumps(text, ensure_ascii=False).replace("<", "\\u003c")
    safe_locale = json.dumps(locale)
    safe_ready = json.dumps(bool(ready))
    messages = {
        "en": ("🔊 Read aloud", "■ Stop", "Prepare a localized summary first."),
        "bn": ("🔊 শুনুন", "■ থামুন", "আগে স্থানীয় ভাষায় সারাংশ তৈরি করুন।"),
        "hi": ("🔊 सुनें", "■ रोकें", "पहले स्थानीय भाषा में सारांश तैयार करें।"),
    }
    play_label, stop_label, prepare_message = messages.get(language, messages["en"])
    safe_prepare_message = json.dumps(prepare_message, ensure_ascii=False).replace("<", "\\u003c")
    html = f"""<!doctype html><html><body style="margin:0;font-family:sans-serif">
<button id="play" style="padding:8px 14px;border:1px solid #888;border-radius:8px;background:#fff;cursor:pointer">{play_label}</button>
<button id="stop" style="margin-left:6px;padding:8px 14px;border:1px solid #888;border-radius:8px;background:#fff;cursor:pointer">{stop_label}</button>
<span id="status" role="status" style="margin-left:8px;font-size:12px"></span>
<script>
const text={safe_text}, lang={safe_locale}, ready={safe_ready}, prepareMessage={safe_prepare_message};
const status=document.getElementById('status');
document.getElementById('play').onclick=()=>{{
  if(!ready){{status.textContent=prepareMessage;return;}}
  if(!('speechSynthesis' in window)){{status.textContent='Speech is not supported in this browser.';return;}}
  window.speechSynthesis.cancel();
  const utterance=new SpeechSynthesisUtterance(text); utterance.lang=lang;
  const chooseVoice=()=>{{
    const voices=window.speechSynthesis.getVoices();
    const exact=voices.find(v=>v.lang.toLowerCase()===lang.toLowerCase());
    const regional=voices.find(v=>v.lang.toLowerCase().startsWith(lang.slice(0,2)));
    const voice=exact||regional; if(voice) utterance.voice=voice;
  }};
  chooseVoice(); utterance.onstart=()=>status.textContent='Playing';
  utterance.onend=()=>status.textContent='';
  utterance.onerror=()=>status.textContent='Speech could not be played.';
  window.speechSynthesis.speak(utterance);
}};
document.getElementById('stop').onclick=()=>{{window.speechSynthesis.cancel();status.textContent='Stopped';}};
</script></body></html>"""
    components.html(html, height=64, scrolling=False, tab_index=0)


def clean_scheme_text(value):
    """Decode catalog text and turn markup/escaped whitespace into readable text."""
    if isinstance(value, list):
        value = "\n".join(str(part) for part in value)
    text = str(value or "")
    for _ in range(5):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = re.sub(r"(?is)<a\b[^>]*href=[\"'](https?://[^\"']+)[\"'][^>]*>(.*?)</a>", r"\2 (\1)", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", " ")
    text = text.replace("\\:", ":").replace("\\/", "/")
    text = text.replace("\\", " ").replace("\xa0", " ").replace("\u200b", "")
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return text.strip()


def scheme_items(value, section):
    """Normalize source lists into concise, nonduplicated bullet items."""
    text = clean_scheme_text(value)
    if not text:
        return []
    if section == "How to apply":
        # Keep rich-text fragments together until the next step or section label.
        text = re.sub(r"(?i)\s*(?=(?:step\s*\d+\s*:|check application status\s*:|find your nearest camp\s*:|help\s*&\s*support\s*:|in general information\s*:))", "\n", text)
        text = re.sub(r"\s*•\s*", " ", text)
    else:
        # myScheme rich text sometimes serializes each list item as a bullet
        # inside one long line; split those markers before removing numbering.
        text = re.sub(r"\s*•\s*", "\n", text)
    raw_lines = [re.sub(r"^\s*(?:(?:[-*•]+)|(?:\d+[.)]))\s*", "", line).strip() for line in text.splitlines()]
    raw_lines = [re.sub(r"\s+", " ", line).strip(" \t-•") for line in raw_lines if line.strip(" \t-•")]
    items = []
    pending_label = None
    for line in raw_lines:
        if not line:
            continue
        # Keep headings and their description together, e.g. "Mode of
        # Disbursement: ..." and "Step 1: Open the site...".
        if pending_label:
            items.append(f"{pending_label} {line}")
            pending_label = None
            continue
        if re.match(r"(?i)^step\s*\d+\s*:$", line) or re.match(r"(?i)^(?:check application status|find your nearest camp|help\s*&\s*support|in general information)\s*:$", line) or (line.endswith(":") and len(line) < 80):
            pending_label = line
            continue
        items.append(line)
    if pending_label:
        items.append(pending_label.rstrip(":"))
    # De-duplicate consecutive artifacts commonly created by <br> and list tags.
    return [item for index, item in enumerate(items) if index == 0 or item.casefold() != items[index - 1].casefold()]


def application_sections(value):
    """Reassemble serialized application instructions into titled bullet groups."""
    text=clean_scheme_text(value)
    if not text: return []
    # Make structural headings and numbered steps boundaries before separating
    # the nested list markers emitted by the source rich-text exporter.
    text=re.sub(r"(?i)\s*(?=(?:steps\s*:|in general information\s*:|help\s*&\s*support\s*:|step\s*\d+\s*:|check application status\s*:|find your nearest camp\s*:))","\n",text)
    pieces=re.split(r"[\n•]+",text)
    parts=[]; current=""; active_section=None; after_support=False; general_added=False
    def flush():
        nonlocal current
        item=re.sub(r"\s+"," ",current).strip(" \t-•")
        if item: parts.append(("item",item,active_section))
        current=""
    for piece in pieces:
        piece=re.sub(r"^\s*(?:(?:[-*]+)|(?:\d+[.)]))\s*","",piece).strip()
        if not piece: continue
        heading=re.match(r"(?i)^(steps|in general information|help\s*&\s*support)\s*:\s*(.*)$",piece)
        if heading:
            flush()
            label="Help & Support" if heading.group(1).casefold().startswith("help") else heading.group(1).title()
            active_section=label
            if label=="Help & Support": after_support=True
            elif label=="In General Information": general_added=True; after_support=False
            parts.append(("heading",label,None))
            remainder=heading.group(2).strip()
            if remainder:
                if label=="Help & Support": parts.append(("contact",remainder,label))
                else: current=remainder
            continue
        step=re.match(r"(?i)^step\s*\d+\s*:\s*(.*)$",piece)
        if step:
            flush()
            if after_support and not general_added:
                parts.append(("heading","In General Information",None))
                active_section="In General Information"; general_added=True; after_support=False
            else:
                active_section=active_section or "Steps"
            remainder=step.group(1).strip()
            if remainder: current=remainder
            continue
        if re.match(r"(?i)^check application status\s*:?$",piece):
            flush(); current="Check Application Status"; flush(); continue
        if current and (re.search(r"[.!?]$",current) or current.casefold()=="check application status"):
            flush()
        if active_section=="Help & Support":
            parts.append(("contact",piece,active_section)); active_section=None; continue
        current=(current+" "+piece).strip() if current else piece
    flush()
    if parts and not any(kind=="heading" and label=="Steps" for kind,label,_ in parts):
        parts.insert(0,("heading","Steps",None))
    if any(kind=="heading" and label=="In General Information" for kind,label,_ in parts):
        support=[part for part in parts if (part[0]=="heading" and part[1]=="Help & Support") or (part[0]=="contact" and part[2]=="Help & Support")]
        parts=[part for part in parts if part not in support]+support
    return parts


def application_cell(value):
    parts=application_sections(value)
    if not parts: return ""
    output=[]; list_open=False
    for kind,text,_section in parts:
        if kind=="heading":
            if list_open: output.append("</ul>"); list_open=False
            output.append(f"<p class='application-heading'><strong>{html.escape(text)}:</strong></p>")
            if text!="Help & Support": output.append("<ul class='scheme-points'>"); list_open=True
        elif kind=="contact":
            output.append(f"<p>{linkify_html(text)}</p>")
        else:
            if not list_open: output.append("<ul class='scheme-points'>"); list_open=True
            output.append(f"<li><strong>{linkify_html(text)}</strong></li>")
    if list_open: output.append("</ul>")
    return "".join(output)


def linkify_html(text):
    escaped = html.escape(text, quote=True)
    return re.sub(r"https?://[^\s<]+", lambda match: _safe_link(match.group(0)), escaped)


def _safe_link(escaped_url):
    url = escaped_url.rstrip(".,;:)")
    suffix = escaped_url[len(url):]
    if not url.startswith(("https://", "http://")):
        return escaped_url
    return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>{suffix}'

st.set_page_config(page_title="Government Schemes Assistant", page_icon="🇮🇳", layout="wide")
st.title("Government Schemes Assistant")
st.caption("Ask about public benefit schemes in English, বাংলা, or हिन्दी.")
logger.debug("Streamlit app initialized")


def show_api_status():
    try:
        health = get("/health")
        status = get("/api/v1/status")
        logger.debug("API readiness confirmed: schemes=%d chunks=%d",status.get("scheme_count",0),status.get("document_chunk_count",0))
        st.sidebar.success("API connected")
        st.sidebar.caption(f"{status['scheme_count']:,} schemes · {status['document_chunk_count']:,} searchable records")
        with st.sidebar.expander("Diagnostics"):
            st.write({"API URL": BASE, "health": health, "status": status})
        return True
    except requests.RequestException as exc:
        logger.exception("API status check failed")
        st.sidebar.error("API is not reachable")
        st.sidebar.caption(f"URL: {BASE}")
        st.sidebar.code(str(exc))
        st.error("The assistant API is unavailable. Start the project with `python scripts/run_project.py`, then reload this page.")
        return False


api_ready = show_api_status()
tab_personalized, tab_browse, tab_compare = st.tabs(["Personalized Discovery", "Browse Schemes", "Compare Schemes"])

with tab_personalized:
    st.subheader("What would you like to know?")
    if api_ready:
        try:
            languages = get("/api/v1/languages")
            lang_labels = {item["native_name"]: item["code"] for item in languages}
            selected_language = st.selectbox("Answer language", list(lang_labels), key="answer_language")
            language = lang_labels[selected_language]
        except requests.RequestException as exc:
            logger.exception("Could not load supported languages")
            language = "en"
            st.warning(f"Could not load language options; using English. Details: {exc}")

        with st.form("question_form", clear_on_submit=False):
            question = st.text_area(
                "Your question",
                placeholder="For example: What schemes are available for unemployed people in West Bengal?",
                height=130,
                key="question_input",
            )
            submitted = st.form_submit_button("Find schemes and answer", type="primary", use_container_width=True)

        streamed_this_run = False
        if submitted:
            if not question.strip():
                st.warning("Type a question above, then click Find schemes and answer.")
            else:
                logger.info("Chat submitted (characters=%d, language=%s)", len(question), language)
                st.session_state.pop("last_answer", None)
                st.session_state.pop("last_question", None)
                started = time.perf_counter()
                progress = st.empty()
                answer_slot = st.empty()
                partial_answer = ""
                activity = []
                result = None
                try:
                    for event in stream_chat({"question": question.strip(), "language": language}):
                        if event.get("type") == "status":
                            activity.append(event.get("message", "Working..."))
                            logger.debug("Chat progress event: %s",event.get("message", "Working..."))
                            progress.markdown("\n\n".join(f"- {item}" for item in activity))
                        elif event.get("type") == "retrieved_sources":
                            items = event.get("items", [])
                            logger.debug("Retrieved source event received: count=%d",len(items))
                            with st.expander(f"Retrieved evidence ({len(items)} passages)", expanded=True):
                                for source in items:
                                    title = source.get("source_title") or source.get("scheme_id") or "Source"
                                    page = f" · page {source['page_number']}" if source.get("page_number") else ""
                                    score = source.get("retrieval_score")
                                    score_label = f" · score {score:.3f}" if isinstance(score, (int, float)) else ""
                                    status_label = source.get("verification_status", "status unknown")
                                    with st.expander(f"[{source.get('citation_id', '?')}] {title}{page} · {status_label}{score_label}"):
                                        st.write(source.get("excerpt") or "No excerpt was provided.")
                                        if source.get("source_url"):
                                            st.link_button("Open source", source["source_url"])
                        elif event.get("type") == "token":
                            partial_answer += event.get("text", "")
                            answer_slot.markdown(partial_answer)
                        elif event.get("type") == "done":
                            result = event.get("result")
                            logger.debug("Chat final event received: evidence=%s citations=%d",result.get("evidence_status","unknown"),len(result.get("citations",[])))
                    if result is None:
                        raise RuntimeError("The streaming response ended before a final result was received.")
                    st.session_state["last_answer"] = result
                    st.session_state["last_question"] = question.strip()
                    streamed_this_run = True
                    elapsed = time.perf_counter() - started
                    progress.success(f"Answer ready in {elapsed:.1f} seconds.")
                    logger.info("Streaming chat completed (evidence=%s, citations=%d, elapsed=%.2fs)",result.get("evidence_status","unknown"),len(result.get("citations",[])),elapsed)
                except requests.RequestException as exc:
                    logger.exception("Streaming chat API request failed")
                    progress.error("The answer stream could not be completed.")
                    st.code(str(exc))
                except Exception as exc:
                    logger.exception("Unexpected error while streaming answer")
                    progress.error("The answer stream ended unexpectedly.")
                    st.code(f"{type(exc).__name__}: {exc}")

        answer = st.session_state.get("last_answer")
        if answer:
            st.divider()
            st.markdown(f"**Question:** {st.session_state.get('last_question', '')}")
            if not streamed_this_run:
                st.markdown(answer.get("answer") or "The API returned an empty answer.")
            answer_text = answer.get("answer") or ""
            if answer_text:
                st.caption("Listen to this answer")
                render_read_aloud(answer_text, answer.get("language", language), ready=True)
            for warning in answer.get("warnings", []):
                st.warning(warning)
            citations = answer.get("citations", [])
            if citations:
                st.subheader("Sources")
                for citation in citations:
                    title = citation.get("source_title") or citation.get("scheme_id") or "Source"
                    with st.expander(f"[{citation.get('citation_id', '?')}] {title} · {citation.get('verification_status', 'status unknown')}"):
                        st.write(citation.get("excerpt") or "No excerpt was provided.")
                        if citation.get("source_url"):
                            st.link_button("Open source", citation["source_url"])
            elif answer.get("evidence_status") == "insufficient":
                st.info("No sufficiently relevant source was found. Try a scheme name, benefit type, or state in your question.")
            else:
                st.info("The response did not include source citations. Check the terminal logs and API diagnostics.")

with tab_browse:
    st.subheader("Browse schemes matched to your profile")
    st.caption("Results are limited to schemes with profile and category evidence in the available scheme records.")
    try:
        browse_catalog = get("/api/v1/schemes") if api_ready else []
        logger.debug("Browse catalog loaded: schemes=%d",len(browse_catalog))
    except requests.RequestException:
        logger.exception("Could not load browse catalog")
        browse_catalog = []
    states = sorted({s.get("state") for s in browse_catalog if s.get("state") and s.get("state").casefold() not in {"all", "india"}})
    categories = sorted({s.get("scheme_category") for s in browse_catalog if s.get("scheme_category")} |
                        {"Education", "Agriculture", "Health Care", "Women and Child Development", "Housing",
                         "Employment", "Social Welfare", "Business", "Financial Inclusion", "Skill Development",
                         "Environment", "Energy", "Rural Development"})
    p1, p2, p3 = st.columns(3)
    with p1:
        browse_state = st.selectbox("State", ["Select state"] + states, key="browse_state")
        browse_age_on = st.checkbox("Use age", key="browse_age_on")
        browse_age = st.number_input("Age", 1, 120, 30, disabled=not browse_age_on, key="browse_age")
    with p2:
        browse_gender = st.selectbox("Gender", ["Prefer not to say", "Female", "Male", "Transgender", "Other"], key="browse_gender")
        browse_category = st.selectbox("Category", ["Select category", "GN", "SC", "ST", "OBC"], key="browse_beneficiary_category")
    with p3:
        browse_income_on = st.checkbox("Use annual income", key="browse_income_on")
        browse_income = st.number_input("Annual Income (₹)", 0, 100000000, 300000, 10000, disabled=not browse_income_on, key="browse_income")
        browse_scheme_category = st.selectbox("Scheme Category", ["All categories"] + categories, key="browse_scheme_category")
    if st.button("Find relevant schemes", type="primary", key="browse_submit"):
        profile = {"state": None if browse_state == "Select state" else browse_state,
                   "age": browse_age if browse_age_on else None,
                   "income": browse_income if browse_income_on else None,
                   "gender": None if browse_gender == "Prefer not to say" else browse_gender,
                   "beneficiary_category": None if browse_category == "Select category" else browse_category,
                   "scheme_category": None if browse_scheme_category == "All categories" else browse_scheme_category}
        try:
            st.session_state["browse_results"] = post("/api/v1/schemes/discover", {"profile": profile})
            st.session_state["browse_profile"] = profile
            logger.debug("Browse discovery completed: supplied_fields=%d results=%d",sum(value is not None for value in profile.values()),len(st.session_state["browse_results"]))
        except requests.RequestException as exc:
            logger.exception("Browse discovery API request failed")
            st.error("Scheme search failed.")
            st.caption(str(exc))
    browse_results = st.session_state.get("browse_results", [])
    if st.session_state.get("browse_profile") and not browse_results:
        st.info("No schemes matched these profile details and category. Try changing the inputs or selecting All categories.")
    for scheme in browse_results:
        with st.container(border=True):
            st.markdown(f"**{scheme['scheme_name']}**")
            if scheme.get("official_source_url"):
                st.markdown(f"**[Open scheme page]({scheme['official_source_url']})**")
            else:
                st.markdown("**Scheme page:** Link unavailable in the catalog.")
            st.markdown("**About Scheme**")
            summary = scheme.get("description") or scheme.get("eligibility_summary") or "Summary unavailable in the catalog."
            st.write(summary if len(summary) <= 500 else summary[:497].rsplit(" ",1)[0] + "…")
            st.markdown("**Benefits**")
            benefits = scheme.get("benefits") or []
            if isinstance(benefits, str): benefits = [x.strip() for x in benefits.splitlines() if x.strip()]
            if benefits:
                for benefit in benefits: st.markdown(f"- {benefit}")
            else: st.caption("Benefits are not listed in the available record.")
            st.markdown("**Documents Required**")
            for document in scheme.get("required_documents") or []: st.markdown(f"- {document}")
            if not scheme.get("required_documents"): st.caption("Document requirements are not listed in the available record.")
            st.markdown("**How to Apply**")
            application = scheme.get("application_process")
            if application:
                for step in [line.strip(" -*\t") for line in application.splitlines() if line.strip()]: st.markdown(f"- {step}")
            else: st.caption("Application steps are not listed in the available record.")

with tab_compare:
    st.subheader("Compare schemes for your profile")
    st.markdown("**Your profile**")
    p1, p2, p3, p4 = st.columns(4)
    with p1: compare_age_on = st.checkbox("Use age", key="compare_age_on"); compare_age = st.number_input("Age",1,120,30,disabled=not compare_age_on,key="compare_age")
    with p2: compare_gender = st.selectbox("Gender",["Prefer not to say","Female","Male","Transgender","Other"],key="compare_gender")
    with p3: compare_category = st.selectbox("Category",["Select category","GN","SC","ST","OBC"],key="compare_category")
    with p4: compare_income_on = st.checkbox("Use annual income",key="compare_income_on"); compare_income = st.number_input("Annual Income (₹)",0,100000000,300000,10000,disabled=not compare_income_on,key="compare_income")
    st.caption("Enter your profile first, then choose two required schemes and up to two more. Profile relevance is calculated separately for each scheme from your age, gender, category, and annual income. Scores appear when the schemes share a category or domain.")
    try:
        compare_catalog = get("/api/v1/schemes") if api_ready else []
        logger.debug("Comparison catalog loaded: schemes=%d",len(compare_catalog))
    except requests.RequestException:
        logger.exception("Could not load comparison catalog")
        compare_catalog = []
    scheme_options = {s["scheme_id"]: s["scheme_name"] for s in compare_catalog}
    options = ["Select a scheme"] + list(scheme_options)
    c1, c2, c3, c4 = st.columns(4)
    with c1: scheme_1 = st.selectbox("Scheme 1 (required)", options, format_func=lambda value: scheme_options.get(value, value), key="compare_scheme_1")
    with c2: scheme_2 = st.selectbox("Scheme 2 (required)", options, format_func=lambda value: scheme_options.get(value, value), key="compare_scheme_2")
    with c3: scheme_3 = st.selectbox("Scheme 3 (optional)", options, format_func=lambda value: scheme_options.get(value, value), key="compare_scheme_3")
    with c4: scheme_4 = st.selectbox("Scheme 4 (optional)", options, format_func=lambda value: scheme_options.get(value, value), key="compare_scheme_4")
    selected = [value for value in (scheme_1,scheme_2,scheme_3,scheme_4) if value != "Select a scheme"]
    valid_selection = scheme_1 != "Select a scheme" and scheme_2 != "Select a scheme" and len(selected) >= 2 and len(set(selected)) == len(selected)
    if st.button("Compare selected schemes",type="primary",disabled=not valid_selection,key="compare_submit"):
        profile={"age":compare_age if compare_age_on else None,
                 "gender":None if compare_gender=="Prefer not to say" else compare_gender,
                 "beneficiary_category":None if compare_category=="Select category" else compare_category,
                 "income":compare_income if compare_income_on else None}
        try:
            st.session_state["comparison_results"]=post("/api/v1/schemes/compare",{"scheme_ids":selected,"profile":profile})
            logger.debug("Scheme comparison completed: selected=%d profile_fields=%d comparable_domain=%s",len(selected),sum(value is not None for value in profile.values()),all(item.get("related_domain_comparison") for item in st.session_state["comparison_results"]))
        except requests.RequestException as exc:
            logger.exception("Scheme comparison API request failed")
            st.error("Comparison could not be loaded."); st.caption(str(exc))
    compared=st.session_state.get("comparison_results",[])
    if compared:
        show_relevance=all(item.get("related_domain_comparison") for item in compared)
        if not show_relevance:
            st.info("These schemes are from unrelated categories or domains, so profile relevance percentages are not shown.")
        def plain_cell(value):
            return linkify_html(clean_scheme_text(value)) if value else ""

        def about_cell(item):
            text=clean_scheme_text(item.get("description") or item.get("eligibility_summary"))
            rendered=linkify_html(text)
            name=html.escape(clean_scheme_text(item.get("scheme_name", "")),quote=True)
            if name:
                rendered=re.sub(re.escape(name),lambda match:f"<strong>{match.group(0)}</strong>",rendered,count=1,flags=re.IGNORECASE)
            return rendered

        def bullet_cell(value,section):
            items=scheme_items(value,section)
            if not items: return ""
            return "<ul class='scheme-points'>"+"".join(f"<li><strong>{linkify_html(item)}</strong></li>" for item in items)+"</ul>"

        row_specs=[("Category",lambda item:plain_cell(item.get("scheme_category"))),
                   ("Profile relevance",lambda item:plain_cell(
                       f"{item['relevance_percentage']}%" if show_relevance and item.get("relevance_percentage") is not None
                       else "")),
                   ("About",about_cell),
                   ("Benefits",lambda item:bullet_cell(item.get("benefits"),"Benefits")),
                   ("Documents required",lambda item:bullet_cell(item.get("required_documents"),"Documents required")),
                   ("How to apply",lambda item:application_cell(item.get("application_process")))]
        rendered_rows=[]
        for label,value_for in row_specs:
            cells=[value_for(item) for item in compared]
            if any(cell.strip() for cell in cells):
                cells=[cell if cell.strip() else "<em>Not available in catalog</em>" for cell in cells]
                rendered_rows.append((label,cells))
        headers="".join(f"<th>{html.escape(clean_scheme_text(item['scheme_name']))}</th>" for item in compared)
        body="".join("<tr><th class='row-label'>"+html.escape(label)+"</th>"+"".join(f"<td>{cell}</td>" for cell in cells)+"</tr>" for label,cells in rendered_rows)
        table=("<style>"
               ".compare-wrap{width:100%;overflow-x:auto}"
               ".compare-table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:15px;line-height:1.55}"
               ".compare-table th,.compare-table td{border:1px solid #58606b;padding:14px 16px;vertical-align:top;overflow-wrap:anywhere;white-space:normal;text-align:left}"
               ".compare-table thead th{position:sticky;top:0;background:#20232a;font-size:16px}"
               ".compare-table .row-label{width:160px;background:#171a20}"
               ".compare-table ul.scheme-points{margin:0;padding-left:24px}"
               ".compare-table li{margin:0 0 12px 0;padding-left:3px}"
               ".compare-table li:last-child{margin-bottom:0}"
               ".compare-table .application-heading{margin:8px 0 5px;font-size:15px}"
               ".compare-table .application-heading:first-child{margin-top:0}"
               ".compare-table p{white-space:normal}"
               ".compare-table a{overflow-wrap:anywhere}"
               "</style><div class='compare-wrap'><table class='compare-table'><thead><tr><th class='row-label'>Details</th>"+headers+"</tr></thead><tbody>"+body+"</tbody></table></div>")
        st.markdown(table,unsafe_allow_html=True)
