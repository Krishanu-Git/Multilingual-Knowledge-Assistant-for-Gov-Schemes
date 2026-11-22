import argparse, json, logging, os
from pathlib import Path
from government_assistant.ingestion import load_records
logging.basicConfig(level=os.getenv("GSA_LOG_LEVEL","DEBUG").upper(),format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger=logging.getLogger("gsa.validate")
p=argparse.ArgumentParser(); p.add_argument("file",type=Path); a=p.parse_args()
try:
 logger.info("Validating scheme data file: file=%s",a.file)
 rows=load_records(a.file); print(json.dumps({"valid":True,"records":len(rows)},indent=2))
 logger.info("Scheme data validation completed: records=%d",len(rows))
except Exception as e:
 logger.exception("Scheme data validation failed")
 print(json.dumps({"valid":False,"error":str(e)},indent=2)); raise SystemExit(1)
