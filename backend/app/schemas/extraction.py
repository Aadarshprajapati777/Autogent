from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TranscriptReference(BaseModel):
    chunk_id: str = Field(description="Exact UUID of a supplied transcript chunk")
    quote: str = Field(min_length=1, max_length=500)


class EvidenceItem(BaseModel):
    references: list[TranscriptReference] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class ExtractedDecision(EvidenceItem):
    title: str = Field(min_length=1, max_length=500)
    rationale: str | None = None


class ExtractedTask(EvidenceItem):
    ref: str = Field(pattern=r"^T[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    owner_name: str | None = None
    deadline: datetime | None = None
    dependency_refs: list[str] = Field(default_factory=list)


class ExtractedRisk(EvidenceItem):
    description: str = Field(min_length=1, max_length=1000)
    severity: str = Field(pattern="^(low|medium|high)$")


class ExtractedQuestion(EvidenceItem):
    question: str = Field(min_length=1, max_length=1000)
    owner_name: str | None = None


class MeetingExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meeting_summary: str = Field(min_length=1, max_length=5000)
    decisions: list[ExtractedDecision] = Field(default_factory=list)
    tasks: list[ExtractedTask] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    risks: list[ExtractedRisk] = Field(default_factory=list)
    questions: list[ExtractedQuestion] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)

    @field_validator("tasks")
    @classmethod
    def refs_unique(cls, tasks: list[ExtractedTask]) -> list[ExtractedTask]:
        if len({task.ref for task in tasks}) != len(tasks):
            raise ValueError("task refs must be unique")
        known = {task.ref for task in tasks}
        if any(
            not set(task.dependency_refs).issubset(known - {task.ref}) for task in tasks
        ):
            raise ValueError("dependencies must reference another extracted task")
        return tasks
