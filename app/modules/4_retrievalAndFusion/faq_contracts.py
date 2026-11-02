"""FAQ authority and evidence identity, independent of document/chunk identities."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from app.models.embedding import canonical_json
from .contracts import RetrievalContractError, json_copy, required_strings


@dataclass(frozen=True)
class FAQIdentity:
    knowledge_base_id: str
    item_id: str
    version: str

    def __post_init__(self):
        required_strings(self.knowledge_base_id, self.item_id, self.version)

    @property
    def parts(self) -> tuple[str, ...]:
        return ("faq", self.knowledge_base_id, self.item_id, self.version)

    @property
    def key(self) -> str:
        return canonical_json(self.parts)

    @classmethod
    def from_key(cls, key: str) -> FAQIdentity:
        try:
            parts = json.loads(key)
        except (TypeError, ValueError) as exc:
            raise RetrievalContractError("invalid FAQ identity") from exc
        if not isinstance(parts, list) or len(parts) != 4 or parts[0] != "faq":
            raise RetrievalContractError("FAQ identity requires kind, knowledge base, item and version")
        return cls(*parts[1:])


@dataclass(frozen=True)
class FAQRecord:
    identity: FAQIdentity
    standard_question: str
    similar_questions: tuple[str, ...]
    answer: str
    conditions: dict[str, Any]
    source: dict[str, Any]

    def __post_init__(self):
        if not isinstance(self.identity, FAQIdentity):
            raise RetrievalContractError("FAQ requires its own complete identity")
        required_strings(self.standard_question, self.answer)
        if not isinstance(self.similar_questions, (tuple, list)):
            raise RetrievalContractError("similar questions must be a sequence of strings")
        required_strings(*self.similar_questions)
        if not isinstance(self.conditions, dict) or not isinstance(self.source, dict) or not self.source:
            raise RetrievalContractError("FAQ requires conditions and non-empty source information")
        object.__setattr__(self, "similar_questions", tuple(self.similar_questions))
        object.__setattr__(self, "conditions", json_copy(self.conditions))
        object.__setattr__(self, "source", json_copy(self.source))

    @property
    def questions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.standard_question, *self.similar_questions)))

    @property
    def text(self) -> str:
        return self.answer

    @property
    def metadata(self) -> dict[str, Any]:
        return self.conditions

    @property
    def parent(self) -> None:
        return None


@dataclass(frozen=True)
class MatchedQuestion:
    question: str
    raw_score: float
