"""In-memory scoped project knowledge service."""

from __future__ import annotations

from .models import MemoryRecord, MemoryWrite, PromotionCandidate
from .retrieval import retrieve_scoped


class MemoryService:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._candidates: dict[str, PromotionCandidate] = {}
        self._next_memory = 0
        self._next_candidate = 0

    def add_tentative(
        self,
        profile_id: str,
        project_id: str,
        thread_id: str,
        text: str,
        source_ids: tuple[str, ...],
    ) -> MemoryRecord:
        return self.write(
            MemoryWrite(
                profile_id,
                project_id,
                thread_id,
                "thread",
                "tentative",
                "model_hypothesis",
                text,
                f"memory:{profile_id}:{project_id}:{thread_id}",
                source_ids,
            )
        )

    def add_project_fact(
        self,
        profile_id: str,
        project_id: str,
        text: str,
        source_ids: tuple[str, ...],
    ) -> MemoryRecord:
        return self.write(
            MemoryWrite(
                profile_id,
                project_id,
                None,
                "project",
                "formal",
                "project_fact",
                text,
                f"memory:{profile_id}:{project_id}",
                source_ids,
            )
        )

    def write(self, item: MemoryWrite) -> MemoryRecord:
        self._next_memory += 1
        record = MemoryRecord(
            f"memory-{self._next_memory}",
            item.profile_id,
            item.project_id,
            item.thread_id,
            item.scope,
            item.status,
            item.fact_type,
            item.text,
            item.content_ref,
            item.source_ids,
            self._next_memory,
            item.pinned,
        )
        self._records[record.memory_id] = record
        return record

    def retrieve(
        self,
        profile_id: str,
        project_id: str,
        thread_id: str,
        query: str,
    ) -> tuple[MemoryRecord, ...]:
        return retrieve_scoped(
            self._records.values(),
            profile_id=profile_id,
            project_id=project_id,
            thread_id=thread_id,
            query=query,
        )

    def propose_cross_project(self, memory_id: str, *, target_project: str) -> PromotionCandidate:
        if memory_id not in self._records:
            raise LookupError("MEMORY_NOT_FOUND")
        self._next_candidate += 1
        candidate = PromotionCandidate(f"promotion-{self._next_candidate}", memory_id, target_project)
        self._candidates[candidate.candidate_id] = candidate
        return candidate

    def decide_promotion(self, candidate_id: str, decision: str) -> None:
        candidate = self._candidates.pop(candidate_id)
        if decision != "ACCEPT":
            return
        source = self._records[candidate.source_memory_id]
        self.write(
            MemoryWrite(
                source.profile_id,
                candidate.target_project,
                None,
                "cross_project",
                "formal",
                source.fact_type,
                source.text,
                source.content_ref,
                source.source_ids,
                source.pinned,
            )
        )


__all__ = ["MemoryService"]
