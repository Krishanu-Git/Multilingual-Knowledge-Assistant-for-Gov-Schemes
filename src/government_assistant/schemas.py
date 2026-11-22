from typing import Any, Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator

Verification = Literal["unverified", "verified", "outdated", "superseded", "needs_review"]


class SchemeRecord(BaseModel):
    scheme_id: str = Field(min_length=1)
    scheme_name: str = Field(min_length=1)
    scheme_name_original: str | None = None
    scheme_name_translations: dict[str, str] = {}
    description: str | None = None
    description_translations: dict[str, str] = {}
    benefits: str | list[str] | None = None
    eligibility_summary: str | None = None
    required_documents: list[str] | None = None
    application_process: str | None = None
    application_url: str | None = None
    scheme_category: str | None = None
    scheme_level: str | None = None
    state: str | None = None
    district: str | None = None
    target_beneficiaries: list[str] | None = None
    responsible_department: str | None = None
    official_source_url: str | None = None
    source_title: str | None = None
    source_type: str | None = None
    source_language: str | None = None
    source_published_date: str | None = None
    source_effective_date: str | None = None
    source_last_verified_date: str | None = None
    source_version: str | None = None
    verification_status: Verification = "unverified"
    verification_evidence: str | None = None
    record_created_at: str | None = None
    record_updated_at: str | None = None
    supersedes_document_id: str | None = None
    ingestion_status: str = "pending"
    eligibility_rules: list[dict[str, Any]] = []

    @field_validator("official_source_url", "application_url")
    @classmethod
    def valid_http_url(cls, value):
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("URL must use http or https")
        return value


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    language: Literal["en", "bn", "hi"] = "en"
    state: str | None = None
    category: str | None = None


class RetrievalRequest(ChatRequest):
    top_k: int | None = Field(default=None, ge=1, le=30)


class EligibilityRequest(BaseModel):
    scheme_id: str
    profile: dict[str, Any] = {}
    language: Literal["en", "bn", "hi"] = "en"


class FeedbackRequest(BaseModel):
    rating: Literal["helpful", "not_helpful"]
    question_id: str | None = None
    comment: str | None = Field(default=None, max_length=1000)
