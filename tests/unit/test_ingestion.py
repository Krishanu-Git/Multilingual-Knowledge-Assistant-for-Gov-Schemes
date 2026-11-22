import json
from pathlib import Path
import pytest
from government_assistant.ingestion import chunk_text, content_hash, load_records, ingest_document
from government_assistant.schemas import SchemeRecord
from government_assistant.storage import Repository

def test_chunk_text_and_hash_are_stable():
    text="A sentence. "*100
    chunks=chunk_text(text,100,20)
    assert len(chunks)>1 and all(chunks)
    assert content_hash("abc")==content_hash("abc")

def test_scheme_requires_stable_id_and_name():
    with pytest.raises(Exception): SchemeRecord(scheme_name="No id")
    record=SchemeRecord(scheme_id="stable-1",scheme_name="Real scheme",official_source_url="https://example.gov")
    assert record.verification_status=="unverified"

def test_import_and_document_ingestion_are_idempotent(tmp_path):
    source=tmp_path/"schemes.json"
    source.write_text(json.dumps([{"scheme_id":"s1","scheme_name":"Scheme One","official_source_url":"https://example.gov/s1"}]))
    record=load_records(source)[0]; repo=Repository(tmp_path/"db.sqlite"); repo.upsert_scheme(record)
    doc=tmp_path/"source.txt"; doc.write_text("Eligibility information. Apply through the department.")
    first=ingest_document(repo,"s1",doc); second=ingest_document(repo,"s1",doc)
    assert first["document_id"]==second["document_id"]
    assert len(repo.chunks())==first["chunks"]
