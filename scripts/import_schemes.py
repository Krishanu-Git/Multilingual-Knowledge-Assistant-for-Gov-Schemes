import argparse, json, logging
from pathlib import Path
from government_assistant.config import settings
from government_assistant.ingestion import load_records
from government_assistant.storage import Repository

logger=logging.getLogger("gsa.import")

def main():
    parser=argparse.ArgumentParser(description="Import curator supplied scheme JSON/CSV records (no network crawling).")
    parser.add_argument("file",type=Path); args=parser.parse_args(); repo=Repository(settings.db_path)
    records=load_records(args.file)
    logger.info("Importing scheme records: count=%d",len(records))
    for record in records: repo.upsert_scheme(record)
    report={"imported":len(records),"scheme_ids":[r.scheme_id for r in records],"source":"local curator import"}
    print(json.dumps(report,indent=2))
    logger.info("Scheme import completed: count=%d",len(records))
if __name__=="__main__": main()
