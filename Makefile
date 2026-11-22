.PHONY: api ui test evaluate
api:
	uvicorn backend.main:app --reload
ui:
	streamlit run frontend/app.py
test:
	pytest
evaluate:
	python scripts/evaluate.py
