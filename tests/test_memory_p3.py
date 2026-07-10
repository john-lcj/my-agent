import time

from memory.base import MemoryItem
from memory.hybrid import HybridMemory
from memory.longterm_sqlite import SQLiteMemory
from memory.vector import MockEmbed, VectorMemory
from memory.evaluation import RetrievalCase, evaluate_top3


def _memory(tmp_path, threshold=0.0):
    return HybridMemory(
        SQLiteMemory(str(tmp_path / "memory.db")),
        VectorMemory(MockEmbed(), str(tmp_path / "vectors.db")),
        min_similarity=threshold,
    )


def test_canonical_identity_and_metadata_are_shared(tmp_path):
    mem = _memory(tmp_path)
    item = MemoryItem(kind="fact", content="Owner works in Shanghai", source="user", confidence=1.4)
    mem.store(item)
    assert item.provenance == "owner_confirmed"
    assert item.confidence == 1.0
    assert mem._kw.get_by_memory_id(item.memory_id)["memory_id"] == item.memory_id
    assert mem._sem.get_by_memory_id(item.memory_id)["memory_id"] == item.memory_id


def test_external_memory_is_quarantined_and_not_recalled(tmp_path):
    mem = _memory(tmp_path)
    item = MemoryItem(kind="fact", content="External page says to ignore policy", source="web")
    mem.store(item)
    assert item.status == "quarantined"
    assert mem.retrieve("ignore policy", k=5) == []
    assert mem.export(include_deleted=True)[0]["status"] == "quarantined"


def test_supersede_and_privacy_delete_are_mirrored(tmp_path):
    mem = _memory(tmp_path)
    old = MemoryItem(kind="preference", content="Prefers email", source="user")
    new = MemoryItem(kind="preference", content="Prefers Slack", source="user")
    mem.store(old)
    mem.supersede(old.memory_id, new)
    assert mem._kw.get_by_memory_id(old.memory_id)["status"] == "superseded"
    assert mem._sem.get_by_memory_id(new.memory_id)["supersedes_id"] == old.memory_id
    assert mem.delete_by_memory_id(new.memory_id)
    assert mem._kw.get_by_memory_id(new.memory_id)["status"] == "deleted"
    assert mem._sem.get_by_memory_id(new.memory_id)["status"] == "deleted"
    assert mem.export() == []


def test_expired_non_fact_is_filtered_and_fact_is_marked_stale(tmp_path):
    mem = _memory(tmp_path)
    expired = time.time() - 100
    fact = MemoryItem(kind="fact", content="Old fact", source="user", expires_at=expired)
    episode = MemoryItem(kind="episode", content="Old episode", source="user", expires_at=expired)
    mem.store(fact)
    mem.store(episode)
    hits = mem.retrieve("Old", k=5)
    assert len(hits) == 1
    assert hits[0].stale is True


def test_keyword_only_factory_does_not_claim_semantic_mock(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_EMBED_ALLOW_MOCK", raising=False)
    monkeypatch.setenv("AGENT_EMBED_PROVIDER", "openai")
    from memory.factory import build_longterm
    mem = build_longterm(str(tmp_path))
    from memory.vector import MockEmbed
    assert mem._sem is None or not isinstance(mem._sem.embed_fn, MockEmbed)


def test_labeled_retrieval_evaluation_reports_top3_precision_and_scope(tmp_path):
    mem = _memory(tmp_path)
    mem.store(MemoryItem(kind="fact", content="Project Atlas deadline Friday", source="user", scope="atlas|web"))
    mem.store(MemoryItem(kind="fact", content="Personal doctor appointment", source="user", scope="personal|web"))
    metrics = evaluate_top3(mem, [RetrievalCase(
        "Atlas deadline", frozenset({"Project Atlas deadline Friday"}), "atlas|web")])
    assert metrics["top3_precision"] == 1.0
    assert metrics["privacy_leak_rate"] == 0.0
