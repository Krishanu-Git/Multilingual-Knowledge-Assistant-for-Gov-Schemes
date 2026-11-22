import json, os, requests
BASE=os.getenv("GSA_API_URL","http://localhost:8000")

def _json_response(response):
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail=response.text[:2000] or str(exc)
        raise requests.HTTPError(f"{exc}\nAPI response: {detail}",request=response.request,response=response) from exc
    return response.json()

def get(path, params=None):
    response=requests.get(BASE+path,params=params,timeout=10); return _json_response(response)
def post(path, payload=None, files=None, data=None):
    response=requests.post(BASE+path,json=payload,files=files,data=data,timeout=150); return _json_response(response)

def stream_chat(payload):
    with requests.post(BASE+"/api/v1/chat/stream",json=payload,headers={"Accept":"text/event-stream"},stream=True,timeout=(10,300)) as response:
        _json_response(response) if response.status_code>=400 else None
        response.encoding=response.encoding or "utf-8"
        for line in response.iter_lines(chunk_size=1,decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data=line[5:].strip()
            if data:
                yield json.loads(data)
