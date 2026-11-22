import csv, hashlib, json, logging, re
from pathlib import Path
from datetime import datetime, timezone
from .schemas import SchemeRecord

logger=logging.getLogger(__name__)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, size=900, overlap=120):
    """Split at paragraph/sentence boundaries where possible, retaining overlap."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text: return []
    chunks=[]; start=0
    while start < len(text):
        end=min(start+size, len(text))
        if end < len(text):
            cut=max(text.rfind(". ", start, end), text.rfind("; ", start, end), text.rfind(" ", start, end))
            if cut > start + size//2: end=cut+1
        value=text[start:end].strip()
        if value: chunks.append(value)
        if end >= len(text): break
        start=max(start+1, end-overlap)
    return chunks


def load_records(path: Path):
    logger.debug("Loading curated scheme records: file=%s",path)
    if path.suffix.lower()==".json":
        data=json.loads(path.read_text(encoding="utf-8")); data=data if isinstance(data,list) else [data]
    elif path.suffix.lower()==".csv":
        with path.open(encoding="utf-8-sig", newline="") as f: data=list(csv.DictReader(f))
        for row in data:
            for key in ("scheme_name_translations", "description_translations", "required_documents", "target_beneficiaries", "eligibility_rules", "benefits"):
                v=row.get(key)
                if isinstance(v,str) and v.strip():
                    try: row[key]=json.loads(v)
                    except json.JSONDecodeError:
                        if key in ("required_documents", "target_beneficiaries"): row[key]=[x.strip() for x in v.split("|") if x.strip()]
    else: raise ValueError("Only JSON and CSV scheme imports are supported")
    normalized=[]
    for row in data:
        row={k:(None if v=="" else v) for k,v in row.items()}
        normalized.append(SchemeRecord.model_validate(row))
    logger.info("Loaded curated scheme records: file=%s count=%d",path,len(normalized))
    return normalized


def extract_document(path: Path):
    suffix=path.suffix.lower()
    logger.debug("Extracting source document text: file=%s format=%s",path.name,suffix)
    if suffix in (".txt", ".md"): return path.read_text(encoding="utf-8")
    if suffix==".html":
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc: raise RuntimeError("Install optional model/document dependencies: pip install -e '.[models]'") from exc
        return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser").get_text("\n", strip=True)
    if suffix==".pdf":
        try: from pypdf import PdfReader
        except ImportError as exc: raise RuntimeError("Install pypdf with pip install -e '.[models]'") from exc
        return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    raise ValueError(f"Unsupported document format: {suffix}")


def ingest_document(repo, scheme_id: str, path: Path, source_title: str | None=None, source_url: str | None=None, page_size=900, overlap=120):
    logger.info("Document ingestion started: scheme_id=%s file=%s",scheme_id,path.name)
    record=repo.get_scheme(scheme_id)
    if not record: raise ValueError(f"Unknown scheme_id: {scheme_id}; import the scheme record first")
    text=extract_document(path); digest=content_hash(text); document_id=f"{scheme_id}:{digest[:16]}"
    pages=text.split("\f") if path.suffix.lower()==".pdf" else [text]
    chunks=[]
    for page_no,page in enumerate(pages,1):
        for idx,part in enumerate(chunk_text(page,page_size,overlap)):
            chash=content_hash(part); chunks.append({"chunk_id":f"{document_id}:{page_no}:{idx}:{chash[:10]}","document_id":document_id,"scheme_id":scheme_id,"source_title":source_title or record.source_title or path.name,"source_url":source_url or record.official_source_url,"page_number":page_no if path.suffix.lower()==".pdf" else None,"section_title":None,"language":record.source_language,"verification_status":record.verification_status,"source_version":record.source_version,"content":part,"content_hash":chash})
    repo.replace_chunks(scheme_id,chunks)
    record.ingestion_status="ingested"; record.record_updated_at=datetime.now(timezone.utc).isoformat(); repo.upsert_scheme(record)
    with repo.connect() as db:
        db.execute("INSERT OR REPLACE INTO documents VALUES (?, ?, ?)",(document_id,scheme_id,json.dumps({"path_name":path.name,"content_hash":digest,"source_title":source_title or path.name,"source_url":source_url or record.official_source_url,"ingested_at":datetime.now(timezone.utc).isoformat()})))
        db.execute("INSERT INTO ingestion_jobs(payload) VALUES (?)",(json.dumps({"document_id":document_id,"scheme_id":scheme_id,"chunks":len(chunks),"status":"success"}),))
    result={"document_id":document_id,"chunks":len(chunks),"content_hash":digest,"status":"success"}
    logger.info("Document ingestion completed: scheme_id=%s document_id=%s chunks=%d",scheme_id,document_id,len(chunks))
    return result
