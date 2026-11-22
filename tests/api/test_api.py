from fastapi.testclient import TestClient
from backend.main import app

client=TestClient(app)
def test_health_and_languages():
    assert client.get("/health").json()["status"]=="ok"
    assert {x["code"] for x in client.get("/api/v1/languages").json()}=={"en","bn","hi"}

def test_chat_empty_catalog_abstains():
    result=client.post("/api/v1/chat",json={"question":"What help is available?","language":"en"}).json()
    assert result["evidence_status"]=="insufficient" and not result["citations"]

def test_speech_empty_rejected():
    response=client.post("/api/v1/speech/transcribe",files={"audio":("empty.wav",b"","audio/wav")},data={"language":"en"})
    assert response.status_code==400
