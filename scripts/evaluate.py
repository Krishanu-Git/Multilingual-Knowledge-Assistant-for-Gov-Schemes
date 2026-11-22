import argparse, json, logging, math
from pathlib import Path
from government_assistant.config import settings
from government_assistant.storage import Repository
from government_assistant.service import AssistantService

logger=logging.getLogger("gsa.evaluate")

def metrics(gold, predictions, k=5):
    recalls=[]; precisions=[]; reciprocal=[]; ndcgs=[]
    for expected,actual in zip(gold,predictions):
        expected=set(expected); actual=actual[:k]
        hits=[1 if x in expected else 0 for x in actual]
        recalls.append(sum(hits)/len(expected) if expected else 0)
        precisions.append(sum(hits)/k)
        ranks=[i+1 for i,h in enumerate(hits) if h]
        reciprocal.append(1/min(ranks) if ranks else 0)
        dcg=sum(h/math.log2(i+2) for i,h in enumerate(hits)); ideal=sum(1/math.log2(i+2) for i in range(min(len(expected),k)))
        ndcgs.append(dcg/ideal if ideal else 0)
    n=len(gold) or 1
    return {"queries":len(gold),"recall_at_k":sum(recalls)/n,"precision_at_k":sum(precisions)/n,"mrr":sum(reciprocal)/n,"ndcg_at_k":sum(ndcgs)/n}

def main():
    p=argparse.ArgumentParser(); p.add_argument("--dataset",type=Path,default=Path("data/evaluation/qa.json")); p.add_argument("--k",type=int,default=5); a=p.parse_args()
    rows=json.loads(a.dataset.read_text()) if a.dataset.exists() else []
    logger.info("Evaluation dataset loaded: records=%d",len(rows))
    if not rows:
        print(json.dumps({"status":"no verified evaluation data","note":"Add manually verified records to data/evaluation/qa.json; no benchmark score is claimed."},indent=2)); return
    service=AssistantService(Repository(settings.db_path)); preds=[]
    for row in rows:
        hits=service.retrieve(row["question"],a.k); preds.append([h["scheme_id"] for h in hits])
    logger.debug("Evaluation retrieval completed: queries=%d",len(rows))
    result=metrics([x["expected_scheme_ids"] for x in rows],preds,a.k); result["status"]="measured"; result["k"]=a.k
    print(json.dumps(result,indent=2))
    logger.info("Evaluation metrics calculated: queries=%d k=%d",len(rows),a.k)
if __name__=="__main__": main()
