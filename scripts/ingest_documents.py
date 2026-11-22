import argparse, json, logging
from pathlib import Path
from government_assistant.config import settings
from government_assistant.ingestion import ingest_document
from government_assistant.storage import Repository

logger=logging.getLogger("gsa.ingest_cli")

def main():
    p=argparse.ArgumentParser(description="Ingest a permitted local source file for a previously imported scheme.")
    p.add_argument("scheme_id"); p.add_argument("file",type=Path); p.add_argument("--title"); p.add_argument("--url"); a=p.parse_args()
    logger.info("Starting document ingestion CLI for scheme_id=%s",a.scheme_id)
    result=ingest_document(Repository(settings.db_path),a.scheme_id,a.file,a.title,a.url,settings.chunk_size,settings.chunk_overlap)
    print(json.dumps(result,indent=2))
if __name__=="__main__": main()
