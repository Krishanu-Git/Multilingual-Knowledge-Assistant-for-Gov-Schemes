"""Collect scheme data when needed and launch the local API and Streamlit UI."""
import argparse
import importlib.util
import logging
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from government_assistant.config import settings
from government_assistant.ingestion import ingest_document, load_records
from government_assistant.storage import Repository

DATA_FILE = ROOT / "data" / "curated" / "myscheme_schemes.json"
TEXT_DIR = ROOT / "data" / "processed" / "myscheme"
logger=logging.getLogger("gsa.launcher")


def ensure_data(refresh):
    has_text = TEXT_DIR.exists() and any(TEXT_DIR.glob("*.txt"))
    if refresh or not DATA_FILE.exists() or not has_text:
        logger.info("Running permitted data preparation step: refresh=%s",refresh)
        subprocess.run([sys.executable, str(ROOT / "scripts" / "gather_data.py"), *( ["--refresh"] if refresh else [])], cwd=ROOT, check=True)
    records = load_records(DATA_FILE)
    repo = Repository(settings.db_path)
    indexed = {chunk["scheme_id"] for chunk in repo.chunks()}
    logger.debug("Preparing local index: records=%d already_indexed=%d",len(records),len(indexed))
    for record in records:
        repo.upsert_scheme(record)
        if record.scheme_id not in indexed:
            slug = record.scheme_id.removeprefix("myscheme-")
            source = TEXT_DIR / f"{slug}.txt"
            if source.exists():
                ingest_document(repo, record.scheme_id, source, record.source_title, record.official_source_url,
                                settings.chunk_size, settings.chunk_overlap)
    print(f"Loaded {len(records)} scheme records into {settings.db_path}", flush=True)
    logger.info("Local scheme data ready: records=%d",len(records))


def main():
    parser = argparse.ArgumentParser(description="Prepare data and launch the government schemes assistant.")
    parser.add_argument("--refresh-data", action="store_true", help="Fetch current scheme listings and details before launch.")
    args = parser.parse_args()
    missing = [name for name in ("fastapi", "uvicorn", "streamlit") if importlib.util.find_spec(name) is None]
    if missing:
        raise SystemExit("Missing app dependencies. Run once: python3 -m pip install -e '.[ui]'")
    ensure_data(args.refresh_data)
    logger.info("Starting Government Schemes Assistant services")

    processes = []
    try:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000", "--log-level", settings.log_level.lower()], cwd=ROOT)
        logger.debug("API process started: pid=%s",api.pid)
        processes.append(api)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if api.poll() is not None:
                raise SystemExit(f"API startup failed with exit code {api.returncode}; check whether port 8000 is already in use.")
            try:
                with urlopen("http://127.0.0.1:8000/health", timeout=1):
                    break
            except (URLError, TimeoutError):
                time.sleep(0.25)
        else:
            raise SystemExit("API did not become healthy within 15 seconds.")
        ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "frontend/app.py", "--server.address", "127.0.0.1", "--server.port", "8501"], cwd=ROOT)
        logger.debug("Streamlit process started: pid=%s",ui.pid)
        processes.append(ui)
        time.sleep(2)
        if ui.poll() is not None:
            raise SystemExit(f"Streamlit startup failed with exit code {ui.returncode}; check whether port 8501 is already in use.")
        print("Assistant running: http://localhost:8501", flush=True)
        print("API docs: http://localhost:8000/docs", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping assistant…", flush=True)
        logger.info("Shutdown requested by user")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                logger.debug("Terminating process: pid=%s",process.pid)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
