"""T25 知识点提炼与 Wiki 数据层测试。

覆盖：向量相似度与降级检索、提炼缓存（同一文章不重复调用模型）、
失败（超时/限流/异常）不中断流程并留待重试、Wiki 条目增改废止合并、
维护者接口（列表/新增/编辑/废止/合并/提炼/用量）与鉴权。
全程使用替身 LLM 客户端，不访问真实 API。
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.admin_wiki import get_llm_client
from app.core.config import Settings
from app.db.enums import (
    ArticleStatus,
    CategoryStatus,
    ExtractionStatus,
    WikiEntrySourceType,
    WikiEntryStatus,
)
from app.db.models import Article, Category, KnowledgeExtraction, Source, WikiEntry, WikiEntryLink
from app.knowledge.llm_client import KnowledgePoint, StaticLlmClient
from app.knowledge.vector import VectorIndex, cosine_similarity, keyword_similarity
from app.services import knowledge_service, wiki_service

NOW = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)


def build_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "test",
        "admin_token": "test-admin-token",
        "admin_actor": "test-admin",
        "database_url": "sqlite+pysqlite:///:memory:",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def make_article(
    session: Session, *, title: str = "Raft 选主流程", url: str = "https://a.example.com/1"
) -> Article:
    category = session.scalars(select(Category).where(Category.name == "AI/机器学习")).first()
    if category is None:
        category = Category(name="AI/机器学习", status=CategoryStatus.ACTIVE)
        session.add(category)
        session.flush()
    source = session.scalars(select(Source)).first()
    if source is None:
        source = Source(name="示例博客", site_url="https://blog.example.com/")
        session.add(source)
        session.flush()
    article = Article(
        title=title,
        content="Raft 通过任期与日志复制实现一致性。",
        summary="摘要",
        url=url,
        source_id=source.id,
        primary_category_id=category.id,
        status=ArticleStatus.NORMAL,
        crawled_at=NOW,
    )
    session.add(article)
    session.commit()
    return article


# ---------------------------------------------------------------------------
# 向量与相似度
# ---------------------------------------------------------------------------


def test_cosine_similarity_basics() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0  # 维度不一致时降级
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_keyword_similarity_is_usable_fallback() -> None:
    high = keyword_similarity("Raft 选主流程", "Raft 选主流程详解")
    low = keyword_similarity("Raft 选主流程", "完全无关的内容")

    assert high > low
    assert keyword_similarity("", "x") == 0.0


def test_vector_index_orders_and_filters_candidates() -> None:
    index = VectorIndex(min_similarity=0.5)
    entries = [
        ("wiki_a", [1.0, 0.0], "A"),
        ("wiki_b", [0.9, 0.1], "B"),
        ("wiki_c", [0.0, 1.0], "C"),
    ]

    results = index.search([1.0, 0.0], entries)

    assert [item.entry_id for item in results][0] == "wiki_a"
    assert "wiki_c" not in [item.entry_id for item in results]

    text_results = index.search_text(
        "Raft 选主流程", [("wiki_a", "Raft 选主流程"), ("wiki_b", "无关")]
    )
    assert text_results[0].entry_id == "wiki_a"


# ---------------------------------------------------------------------------
# 提炼与缓存
# ---------------------------------------------------------------------------


def test_extraction_is_cached_per_article(db_session: Session) -> None:
    """同一内容不重复调用外部模型。"""

    article = make_article(db_session)
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程", summary="一致性协议")])

    first = knowledge_service.extract_points(
        db_session, article, client=client, settings=build_settings()
    )
    second = knowledge_service.extract_points(
        db_session, article, client=client, settings=build_settings()
    )

    assert first.status is ExtractionStatus.OK
    assert first.id == second.id
    assert len(client.extract_calls) == 1  # 缓存命中：只调用一次
    assert second.points[0]["name"] == "Raft 选主流程"


def test_extraction_refreshes_when_content_changes(db_session: Session) -> None:
    article = make_article(db_session)
    client = StaticLlmClient(points=[KnowledgePoint(name="旧知识点")])
    knowledge_service.extract_points(db_session, article, client=client, settings=build_settings())

    article.content = "内容发生了实质变化"
    db_session.commit()
    refreshed = knowledge_service.extract_points(
        db_session, article, client=client, settings=build_settings()
    )

    assert len(client.extract_calls) == 2
    assert refreshed.status is ExtractionStatus.OK


def test_extraction_force_bypasses_cache(db_session: Session) -> None:
    article = make_article(db_session)
    client = StaticLlmClient(points=[KnowledgePoint(name="知识点")])
    knowledge_service.extract_points(db_session, article, client=client, settings=build_settings())
    knowledge_service.extract_points(
        db_session, article, client=client, settings=build_settings(), force=True
    )

    assert len(client.extract_calls) == 2


def test_llm_failure_is_recorded_and_does_not_raise(db_session: Session) -> None:
    """超时/限流等失败必须被记录，不能中断流程。"""

    article = make_article(db_session)
    client = StaticLlmClient(points=[], fail_times=5)

    row = knowledge_service.extract_points(
        db_session, article, client=client, settings=build_settings()
    )

    assert row.status is ExtractionStatus.FAILED
    assert row.attempts == 1
    assert row.error and "LLM" in row.error

    # 待判定文章可被后续轮次重试
    assert article in knowledge_service.pending_articles(db_session)


def test_unexpected_client_exception_is_captured(db_session: Session) -> None:
    article = make_article(db_session)

    class BoomClient(StaticLlmClient):
        def extract_points(self, *, title: str, content: str):  # noqa: ANN201
            raise RuntimeError("网络抖动")

    row = knowledge_service.extract_points(
        db_session, article, client=BoomClient(), settings=build_settings()
    )

    assert row.status is ExtractionStatus.FAILED
    assert "网络抖动" in (row.error or "")


def test_retry_after_failure_succeeds(db_session: Session) -> None:
    article = make_article(db_session)
    client = StaticLlmClient(points=[KnowledgePoint(name="恢复后的知识点")], fail_times=1)

    failed = knowledge_service.extract_points(
        db_session, article, client=client, settings=build_settings()
    )
    assert failed.status is ExtractionStatus.FAILED

    recovered = knowledge_service.extract_points(
        db_session, article, client=client, settings=build_settings()
    )
    assert recovered.status is ExtractionStatus.OK
    assert recovered.attempts == 2
    assert recovered.points[0]["name"] == "恢复后的知识点"


def test_usage_stats_counts_calls_tokens_and_failures(db_session: Session) -> None:
    ok_article = make_article(db_session, url="https://a.example.com/ok")
    fail_article = make_article(db_session, title="另一篇", url="https://a.example.com/fail")

    knowledge_service.extract_points(
        db_session,
        ok_article,
        client=StaticLlmClient(points=[KnowledgePoint(name="知识点")]),
        settings=build_settings(),
    )
    knowledge_service.extract_points(
        db_session,
        fail_article,
        client=StaticLlmClient(points=[], fail_times=1),
        settings=build_settings(),
    )

    stats = knowledge_service.usage_stats(db_session)

    assert stats["calls_today"] == 2
    assert stats["failures_today"] == 1
    assert stats["records_total"] == 2


# ---------------------------------------------------------------------------
# Wiki 条目维护
# ---------------------------------------------------------------------------


def test_wiki_entry_crud_and_retire(db_session: Session) -> None:
    article = make_article(db_session)
    entry = wiki_service.create_entry(
        db_session,
        name="Raft 选主流程",
        summary="任期 + 日志复制",
        article_ids=[article.id],
        human_note="人工整理",
    )

    assert entry.status is WikiEntryStatus.ACTIVE
    assert wiki_service.entry_article_ids(db_session, entry.id) == [article.id]

    updated = wiki_service.update_entry(
        db_session, entry.id, name="Raft 选主（修订）", summary="更新摘要"
    )
    assert updated.name == "Raft 选主（修订）"

    retired = wiki_service.retire_entry(db_session, entry.id)
    assert retired.status is WikiEntryStatus.RETIRED
    assert wiki_service.active_candidates(db_session) == []  # 废止后不再进入候选


def test_wiki_entry_validation(db_session: Session) -> None:
    from app.core.errors import ApiError

    with pytest.raises(ApiError):
        wiki_service.create_entry(db_session, name="   ")

    with pytest.raises(ApiError):
        wiki_service.get_entry(db_session, "wiki_missing")


def test_merge_entries_marks_sources_and_links_articles(db_session: Session) -> None:
    first_article = make_article(db_session, url="https://a.example.com/1")
    second_article = make_article(db_session, title="另一篇", url="https://a.example.com/2")
    first = wiki_service.create_entry(db_session, name="知识点 A", article_ids=[first_article.id])
    second = wiki_service.create_entry(db_session, name="知识点 B", article_ids=[second_article.id])

    merged = wiki_service.merge_entries(
        db_session,
        source_entry_ids=[first.id, second.id],
        target_name="知识点 A + B",
        target_summary="合并后的知识点",
    )

    assert merged.status is WikiEntryStatus.ACTIVE
    assert set(wiki_service.entry_article_ids(db_session, merged.id)) == {
        first_article.id,
        second_article.id,
    }
    assert db_session.get(WikiEntry, first.id).status is WikiEntryStatus.MERGED
    assert db_session.get(WikiEntry, first.id).merged_into_id == merged.id


def test_merge_requires_active_sources(db_session: Session) -> None:
    from app.core.errors import ApiError

    first = wiki_service.create_entry(db_session, name="知识点 A")
    second = wiki_service.create_entry(db_session, name="知识点 B")
    wiki_service.retire_entry(db_session, first.id)

    with pytest.raises(ApiError) as error:
        wiki_service.merge_entries(
            db_session, source_entry_ids=[first.id, second.id], target_name="合并"
        )
    assert error.value.code == "WIKI_ENTRY_CONFLICT"

    with pytest.raises(ApiError):
        wiki_service.merge_entries(db_session, source_entry_ids=[second.id], target_name="合并")


def test_list_entries_filters_by_status_and_query(db_session: Session) -> None:
    wiki_service.create_entry(db_session, name="Raft 选主流程")
    wiki_service.create_entry(db_session, name="向量索引优化")
    retired = wiki_service.create_entry(db_session, name="已废止条目")
    wiki_service.retire_entry(db_session, retired.id)

    total, items = wiki_service.list_entries(db_session)
    assert total == 3

    active_total, active_items = wiki_service.list_entries(db_session, status="active")
    assert active_total == 2
    assert all(item.status is WikiEntryStatus.ACTIVE for item in active_items)

    found_total, found = wiki_service.list_entries(db_session, query="向量")
    assert found_total == 1 and found[0].name == "向量索引优化"

    from app.core.errors import ApiError

    with pytest.raises(ApiError):
        wiki_service.list_entries(db_session, status="unknown")


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------


@pytest.fixture()
def scripted_client() -> StaticLlmClient:
    return StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程", summary="一致性协议")])


@pytest.fixture()
def wiki_client(api_app: FastAPI, scripted_client: StaticLlmClient) -> TestClient:
    """覆盖 LLM 客户端依赖的维护者客户端（不访问真实 API）。"""

    api_app.dependency_overrides[get_llm_client] = lambda: scripted_client
    with TestClient(api_app) as test_client:
        yield test_client
    api_app.dependency_overrides.pop(get_llm_client, None)


def test_wiki_admin_api_crud(
    wiki_client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    created = wiki_client.post(
        "/api/v1/admin/wiki/entries",
        headers=admin_headers,
        json={"name": "Raft 选主流程", "summary": "任期 + 日志复制", "note": "人工录入"},
    )
    assert created.status_code == 201
    entry = created.json()
    assert entry["status"] == "active"
    assert entry["created_by"] == WikiEntrySourceType.HUMAN.value

    listed = wiki_client.get("/api/v1/admin/wiki/entries", headers=admin_headers)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    patched = wiki_client.patch(
        f"/api/v1/admin/wiki/entries/{entry['id']}",
        headers=admin_headers,
        json={"summary": "更新后的摘要"},
    )
    assert patched.status_code == 200
    assert patched.json()["summary"] == "更新后的摘要"

    filtered = wiki_client.get(
        "/api/v1/admin/wiki/entries", headers=admin_headers, params={"query": "Raft"}
    )
    assert filtered.json()["total"] == 1

    second = wiki_client.post(
        "/api/v1/admin/wiki/entries", headers=admin_headers, json={"name": "日志压缩"}
    )
    merged = wiki_client.post(
        "/api/v1/admin/wiki/entries/merge",
        headers=admin_headers,
        json={
            "source_entry_ids": [entry["id"], second.json()["id"]],
            "name": "Raft 相关知识点",
            "summary": "合并",
        },
    )
    assert merged.status_code == 200
    assert merged.json()["source_article_ids"] == []

    retired = wiki_client.post(
        f"/api/v1/admin/wiki/entries/{entry['id']}/retire", headers=admin_headers
    )
    assert retired.status_code == 200
    assert retired.json()["status"] == "retired"

    invalid_merge = wiki_client.post(
        "/api/v1/admin/wiki/entries/merge",
        headers=admin_headers,
        json={"source_entry_ids": [second.json()["id"]], "name": "只有一个"},
    )
    assert invalid_merge.status_code == 422  # 校验层拦截（至少两个来源）

    missing = wiki_client.patch(
        "/api/v1/admin/wiki/entries/wiki_missing", headers=admin_headers, json={"summary": "x"}
    )
    assert missing.status_code == 404


def test_knowledge_extract_and_usage_api(
    wiki_client: TestClient,
    admin_headers: dict[str, str],
    api_session: Session,
    scripted_client: StaticLlmClient,
) -> None:
    article = make_article(api_session)

    first = wiki_client.post(f"/api/v1/admin/knowledge/extract/{article.id}", headers=admin_headers)
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "ok"
    assert body["points"][0]["name"] == "Raft 选主流程"
    assert body["model"] == build_settings().llm_model

    second = wiki_client.post(
        f"/api/v1/admin/knowledge/extract/{article.id}", headers=admin_headers
    )
    assert second.status_code == 200
    assert len(scripted_client.extract_calls) == 1  # 缓存生效

    forced = wiki_client.post(
        f"/api/v1/admin/knowledge/extract/{article.id}",
        headers=admin_headers,
        params={"force": True},
    )
    assert forced.status_code == 200
    assert len(scripted_client.extract_calls) == 2

    usage = wiki_client.get("/api/v1/admin/knowledge/usage", headers=admin_headers)
    assert usage.status_code == 200
    assert usage.json()["records_total"] == 1
    assert usage.json()["calls_today"] >= 1

    missing = wiki_client.post(
        "/api/v1/admin/knowledge/extract/article_missing", headers=admin_headers
    )
    assert missing.status_code == 404
    assert api_session.scalar(select(func.count()).select_from(KnowledgeExtraction)) == 1


def test_wiki_endpoints_require_authorization(wiki_client: TestClient) -> None:
    for method, path, payload in (
        ("get", "/api/v1/admin/wiki/entries", None),
        ("post", "/api/v1/admin/wiki/entries", {"name": "x"}),
        ("post", "/api/v1/admin/wiki/entries/merge", {"source_entry_ids": ["a", "b"], "name": "x"}),
        ("post", "/api/v1/admin/wiki/entries/wiki_x/retire", None),
        ("get", "/api/v1/admin/knowledge/usage", None),
        ("post", "/api/v1/admin/knowledge/extract/article_x", None),
    ):
        call = getattr(wiki_client, method)
        response = call(path, json=payload) if payload is not None else call(path)
        assert response.status_code in (401, 403), f"{method} {path} 未拒绝未授权访问"


def test_extraction_table_links_article_and_wiki(db_session: Session) -> None:
    """数据层关联：提炼记录、条目与文章三者可互相追溯。"""

    article = make_article(db_session)
    knowledge_service.extract_points(
        db_session,
        article,
        client=StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")]),
        settings=build_settings(),
    )
    entry = wiki_service.create_entry(db_session, name="Raft 选主流程", article_ids=[article.id])

    row = knowledge_service.get_extraction(db_session, article.id)
    assert row is not None and row.article_id == article.id
    assert db_session.scalar(select(func.count()).select_from(WikiEntryLink)) == 1
    assert wiki_service.find_active_by_name(db_session, "Raft 选主流程").id == entry.id
