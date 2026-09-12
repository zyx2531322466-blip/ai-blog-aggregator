"""T26 知识匹配判定与文章处置测试。

重点验证"保守优先"与"不干扰既有去重"：
- 全新知识 → 正常展示并补写 Wiki；部分新增 → 正常展示 + 新增条目；
- 知识已覆盖 → 归档（不进公开列表、不进推送）；
- **任何不确定情形都不得判为已覆盖**（模型异常、二次判定不确定、无向量）；
- 人工改判优先，并能改变文章的展示与归档状态；
- 判定留痕含依据、相似度、模型与提示词版本；既有文本级去重行为不变。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.admin_wiki import get_llm_client
from app.core.config import Settings, get_settings
from app.db.enums import (
    ArticleStatus,
    CategoryStatus,
    DecisionActor,
    DedupRelationType,
    DigestStatus,
    KnowledgeDecisionType,
    KnowledgeStatus,
    SubscriptionTopicType,
    UpdateFrequency,
)
from app.db.models import (
    Article,
    Category,
    DuplicateRelation,
    KnowledgeDecision,
    Source,
    WikiEntry,
)
from app.knowledge.llm_client import KnowledgePoint, LlmError, StaticLlmClient
from app.notifications.mailer import RecordingMailSender
from app.services import digest_service, knowledge_dedup_service, subscription_service, wiki_service
from app.services.subscription_service import TopicInput

NOW = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)
VECTOR_A = [1.0, 0.0, 0.0]
VECTOR_B = [0.0, 1.0, 0.0]
# 与 VECTOR_A 的余弦相似度约为 0.995（≥ 高阈值）
VECTOR_A_NEAR = [1.0, 0.1, 0.0]
# 与 VECTOR_A 的余弦相似度约为 0.88（落在中间区间 0.80~0.92 → 需要二次判定）
VECTOR_MID_NEAR = [1.0, 0.55, 0.0]


def build_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "test",
        "admin_token": "test-admin-token",
        "admin_actor": "test-admin",
        "database_url": "sqlite+pysqlite:///:memory:",
        "knowledge_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def make_category(session: Session, name: str = "AI/机器学习") -> Category:
    category = session.scalars(select(Category).where(Category.name == name)).first()
    if category is None:
        category = Category(name=name, status=CategoryStatus.ACTIVE)
        session.add(category)
        session.commit()
    return category


def make_source(session: Session) -> Source:
    source = session.scalars(select(Source)).first()
    if source is None:
        source = Source(name="示例博客", site_url="https://blog.example.com/")
        session.add(source)
        session.commit()
    return source


def make_article(
    session: Session,
    *,
    title: str = "Raft 一致性协议解析",
    content: str = "Raft 通过任期与日志复制实现一致性。",
    url: str = "https://a.example.com/1",
) -> Article:
    article = Article(
        title=title,
        content=content,
        summary="摘要",
        url=url,
        source_id=make_source(session).id,
        primary_category_id=make_category(session).id,
        status=ArticleStatus.NORMAL,
        crawled_at=NOW,
    )
    session.add(article)
    session.commit()
    return article


def entry_with_vector(
    session: Session, name: str, embedding: list[float], summary: str = "已有知识点"
) -> WikiEntry:
    return wiki_service.create_entry(session, name=name, summary=summary, embedding=embedding)


# ---------------------------------------------------------------------------
# 三态判定
# ---------------------------------------------------------------------------


def test_new_knowledge_is_kept_and_written_into_wiki(db_session: Session) -> None:
    article = make_article(db_session)
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程", summary="任期选举")])

    outcome = knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    assert outcome.decision is KnowledgeDecisionType.NEW
    assert outcome.archived is False
    assert article.status is ArticleStatus.NORMAL
    assert article.knowledge_status is KnowledgeStatus.NEW
    assert wiki_service.find_active_by_name(db_session, "Raft 选主流程") is not None


def test_covered_knowledge_is_archived(db_session: Session) -> None:
    """已覆盖 → 归档：不进公开列表、不进推送。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/covered")
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR)

    outcome = knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    assert outcome.decision is KnowledgeDecisionType.COVERED
    assert outcome.archived is True
    assert article.status is ArticleStatus.KNOWLEDGE_DUPLICATE
    assert article.knowledge_status is KnowledgeStatus.COVERED


def test_partial_knowledge_adds_only_new_points(db_session: Session) -> None:
    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/partial")
    client = StaticLlmClient(
        points=[KnowledgePoint(name="Raft 选主流程"), KnowledgePoint(name="日志压缩策略")],
        embeddings={"Raft": VECTOR_A_NEAR, "日志压缩": VECTOR_B},  # 第二个点语义无关 → 新增
    )

    outcome = knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    assert outcome.decision is KnowledgeDecisionType.PARTIAL
    assert article.knowledge_status is KnowledgeStatus.PARTIAL
    assert article.status is ArticleStatus.NORMAL
    assert wiki_service.find_active_by_name(db_session, "日志压缩策略") is not None


def test_low_similarity_point_is_new_knowledge(db_session: Session) -> None:
    """相似度低于下限 → 直接判新增（连二次判定都不需要）。"""

    entry_with_vector(db_session, "完全不同的知识点", VECTOR_B)
    article = make_article(db_session, url="https://a.example.com/low")
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A)

    outcome = knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    assert outcome.decision is KnowledgeDecisionType.NEW


# ---------------------------------------------------------------------------
# 保守原则（负向用例是这张票的核心）
# ---------------------------------------------------------------------------


def test_middle_band_without_model_approval_is_not_covered(db_session: Session) -> None:
    """中间区间 + 二次判定返回"未覆盖" → 判新增，绝不归档。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/mid")
    client = StaticLlmClient(
        points=[KnowledgePoint(name="Raft 选主流程（补充实测）")],
        embedding=VECTOR_MID_NEAR,
        cover_when=None,  # 二次判定返回 False
    )

    outcome = knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    assert outcome.archived is False
    assert article.status is not ArticleStatus.KNOWLEDGE_DUPLICATE
    assert client.judge_calls  # 确实走了二次判定


def test_middle_band_with_model_approval_is_covered(db_session: Session) -> None:
    """中间区间 + 模型明确判定"无新增信息" → 才允许归档。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/mid-covered")
    client = StaticLlmClient(
        points=[KnowledgePoint(name="Raft 选主流程")],
        embedding=VECTOR_MID_NEAR,
        cover_when="Raft",
    )

    outcome = knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    assert outcome.decision is KnowledgeDecisionType.COVERED
    assert outcome.archived is True


def test_judge_exception_falls_back_to_new_knowledge(db_session: Session) -> None:
    """二次判定抛异常 → 保守判新增（不能因为异常把文章藏起来）。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/broken-judge")

    class BrokenJudge(StaticLlmClient):
        def judge_coverage(self, *, point, entry_name, entry_summary):  # noqa: ANN001, ANN201
            raise LlmError("二次判定服务不可用")

    outcome = knowledge_dedup_service.judge_article(
        db_session,
        article,
        client=BrokenJudge(
            points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_MID_NEAR
        ),
        settings=build_settings(),
        now=NOW,
    )

    assert outcome.archived is False
    assert article.knowledge_status is KnowledgeStatus.NEW


def test_extraction_failure_marks_pending_and_never_archives(db_session: Session) -> None:
    """模型不可用 → 待判定：不归档、不推送，留待重试。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/pending")
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")], fail_times=5)

    outcome = knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    assert outcome.decision is KnowledgeDecisionType.PENDING
    assert outcome.archived is False
    assert article.knowledge_status is KnowledgeStatus.PENDING
    assert article.status is not ArticleStatus.KNOWLEDGE_DUPLICATE
    assert knowledge_dedup_service.candidate_articles(db_session) == [article]  # 可重试


def test_pending_article_is_retried_on_next_run(db_session: Session) -> None:
    """待判定文章在下一轮被重新处理并转为终态。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/retry")
    failing = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")], fail_times=1)
    knowledge_dedup_service.judge_article(
        db_session, article, client=failing, settings=build_settings(), now=NOW
    )
    assert article.knowledge_status is KnowledgeStatus.PENDING

    working = StaticLlmClient(
        points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR
    )
    outcomes = knowledge_dedup_service.process_articles(
        db_session, client=working, settings=build_settings(), now=NOW
    )

    assert [item.decision for item in outcomes] == [KnowledgeDecisionType.COVERED]
    assert article.status is ArticleStatus.KNOWLEDGE_DUPLICATE


def test_missing_embedding_falls_back_to_text_similarity(db_session: Session) -> None:
    """没有向量（例如人工录入条目）时退化为文本相似度，仍然可以判定覆盖。"""

    wiki_service.create_entry(db_session, name="Raft 选主流程", summary="任期 + 日志复制")
    article = make_article(db_session, url="https://a.example.com/no-vector")

    class NoEmbeddingClient(StaticLlmClient):
        def embed(self, text: str) -> list[float] | None:  # noqa: ANN201
            return None

    outcome = knowledge_dedup_service.judge_article(
        db_session,
        article,
        client=NoEmbeddingClient(
            points=[KnowledgePoint(name="Raft 选主流程", summary="任期 + 日志复制")]
        ),
        settings=build_settings(),
        now=NOW,
    )

    assert outcome.decision in {KnowledgeDecisionType.COVERED, KnowledgeDecisionType.PARTIAL}
    assert outcome.similarity is not None and outcome.similarity >= 0.8


def test_no_points_means_new_content(db_session: Session) -> None:
    article = make_article(db_session, url="https://a.example.com/no-points")
    client = StaticLlmClient(points=[])

    outcome = knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    assert outcome.decision is KnowledgeDecisionType.NEW
    assert article.knowledge_status is KnowledgeStatus.NEW


# ---------------------------------------------------------------------------
# 留痕、人工改判与统计
# ---------------------------------------------------------------------------


def test_decision_record_contains_evidence_and_versions(db_session: Session) -> None:
    entry = entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/evidence")
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR)

    knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )
    row = knowledge_dedup_service.latest_decision(db_session, article.id)

    assert row is not None
    assert row.decision is KnowledgeDecisionType.COVERED
    assert row.matched_entry_id == entry.id
    assert row.similarity is not None and row.similarity > 0.9
    assert row.rationale and "覆盖" in row.rationale
    assert row.model == build_settings().llm_model
    assert row.prompt_version == build_settings().knowledge_prompt_version
    assert row.actor is DecisionActor.SYSTEM
    assert row.points[0]["name"] == "Raft 选主流程"
    assert row.points[0]["is_new"] is False


def test_human_override_wins_and_restores_visibility(db_session: Session) -> None:
    """人工改判为"不是知识重复" → 文章重新可见；改判记录 actor=human。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/override")
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR)
    knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )
    assert article.status is ArticleStatus.KNOWLEDGE_DUPLICATE

    row = knowledge_dedup_service.override_article(
        db_session,
        article.id,
        decision=KnowledgeDecisionType.NEW,
        reason="该文包含实测数据，属于新增信息",
        actor="maintainer",
        settings=build_settings(),
    )

    assert row.actor is DecisionActor.HUMAN
    assert row.rationale and "维护者改判" in row.rationale
    assert article.status is ArticleStatus.NORMAL
    assert article.knowledge_status is KnowledgeStatus.NEW
    assert knowledge_dedup_service.latest_decision(db_session, article.id).id == row.id

    with pytest.raises(Exception):
        knowledge_dedup_service.override_article(
            db_session, "article_missing", decision=KnowledgeDecisionType.NEW, reason="x"
        )


def test_knowledge_stats_and_disabled_switch(db_session: Session) -> None:
    """统计可用于评估是否过严；开关关闭时不做任何判定。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/stats")
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR)
    knowledge_dedup_service.judge_article(
        db_session, article, client=client, settings=build_settings(), now=NOW
    )

    stats = knowledge_dedup_service.knowledge_stats(db_session, settings=build_settings())
    assert stats["filtered_total"] == 1
    assert stats["by_category"]["AI/机器学习"] == 1
    assert stats["llm_usage"]["records_total"] == 1

    disabled = build_settings(knowledge_enabled=False)
    other = make_article(db_session, title="另一篇", url="https://a.example.com/disabled")
    outcome = knowledge_dedup_service.judge_article(
        db_session, other, client=client, settings=disabled, now=NOW
    )
    assert outcome.skipped is True
    assert other.knowledge_status is None
    assert (
        knowledge_dedup_service.process_articles(
            db_session, client=client, settings=disabled, now=NOW
        )
        == []
    )


def test_llm_call_cap_and_batch_isolation(db_session: Session) -> None:
    """单轮调用上限生效；单篇异常不影响其他文章。"""

    for index in range(3):
        make_article(db_session, title=f"文章 {index}", url=f"https://a.example.com/cap-{index}")
    client = StaticLlmClient(points=[KnowledgePoint(name="知识点")])

    outcomes = knowledge_dedup_service.process_articles(
        db_session, client=client, settings=build_settings(llm_max_calls_per_run=2), now=NOW
    )
    assert len(outcomes) == 2

    class PartiallyBrokenClient(StaticLlmClient):
        def extract_points(self, *, title: str, content: str):  # noqa: ANN201
            if "文章 2" in title:
                raise RuntimeError("意外异常")
            return super().extract_points(title=title, content=content)

    rest = knowledge_dedup_service.process_articles(
        db_session,
        client=PartiallyBrokenClient(points=[KnowledgePoint(name="知识点 2")]),
        settings=build_settings(),
        now=NOW,
    )
    assert all(item.decision is not KnowledgeDecisionType.COVERED for item in rest)


# ---------------------------------------------------------------------------
# 与公开列表 / 推送 / 既有去重的联动
# ---------------------------------------------------------------------------


def test_public_list_excludes_archived_and_exposes_knowledge_fields(
    client: TestClient, api_session: Session
) -> None:
    entry_with_vector(api_session, "Raft 选主流程", VECTOR_A)
    archived = make_article(api_session, title="知识重复文章", url="https://a.example.com/archived")
    kept = make_article(api_session, title="全新知识文章", url="https://a.example.com/kept")
    knowledge_dedup_service.judge_article(
        api_session,
        archived,
        client=StaticLlmClient(
            points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR
        ),
        settings=build_settings(),
        now=NOW,
    )
    knowledge_dedup_service.judge_article(
        api_session,
        kept,
        client=StaticLlmClient(points=[KnowledgePoint(name="日志压缩策略")], embedding=VECTOR_B),
        settings=build_settings(),
        now=NOW,
    )

    listing = client.get("/api/v1/articles").json()
    titles = [item["title"] for item in listing["items"]]
    assert titles == ["全新知识文章"]
    item = listing["items"][0]
    assert item["knowledge_status"] == "new"
    assert item["knowledge_points"] == ["日志压缩策略"]

    detail = client.get(f"/api/v1/articles/{kept.id}").json()
    assert detail["knowledge"]["status"] == "new"
    assert detail["knowledge"]["points"][0]["name"] == "日志压缩策略"

    archived_detail = client.get(f"/api/v1/articles/{archived.id}").json()
    assert archived_detail["knowledge"]["status"] == "covered"
    assert archived_detail["knowledge"]["decision_reason"]


def test_digest_skips_covered_and_pending_articles(db_session: Session) -> None:
    """推送过滤：知识已覆盖 / 待判定 的文章不会出现在摘要里。"""

    make_category(db_session)
    covered = make_article(db_session, title="已覆盖", url="https://a.example.com/d-covered")
    covered.status = ArticleStatus.KNOWLEDGE_DUPLICATE
    covered.knowledge_status = KnowledgeStatus.COVERED
    pending = make_article(db_session, title="待判定", url="https://a.example.com/d-pending")
    pending.knowledge_status = KnowledgeStatus.PENDING
    fresh = make_article(db_session, title="全新", url="https://a.example.com/d-new")
    fresh.knowledge_status = KnowledgeStatus.NEW
    db_session.commit()

    subscription, confirm_token = subscription_service.create_subscription(
        db_session,
        email="reader@example.com",
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
        frequency="daily",
    )
    subscription_service.confirm_subscription(db_session, confirm_token)
    db_session.refresh(subscription)
    subscription.confirmed_at = NOW - timedelta(days=2)
    db_session.commit()

    entries = digest_service.collect_entries(db_session, subscription, now=NOW)

    assert [entry.article_id for entry in entries] == [fresh.id]

    sender = RecordingMailSender()
    digest = digest_service.process_subscription(db_session, subscription, sender=sender, now=NOW)
    assert digest is not None and digest.status is DigestStatus.SENT
    assert "全新" in sender.messages[0].text_body
    assert "已覆盖" not in sender.messages[0].text_body
    assert "待判定" not in sender.messages[0].text_body


def test_text_level_dedup_behaviour_unchanged(db_session: Session) -> None:
    """知识级判定不得改动既有合并组与主记录语义。"""

    primary = make_article(db_session, title="原文", url="https://a.example.com/p")
    mirror = make_article(db_session, title="镜像", url="https://b.example.com/p")
    for article, is_primary in ((primary, True), (mirror, False)):
        db_session.add(
            DuplicateRelation(
                group_key="group_t26",
                relation_type=DedupRelationType.EXACT_DUPLICATE,
                article_id=article.id,
                is_primary=is_primary,
            )
        )
    db_session.commit()

    client = StaticLlmClient(points=[KnowledgePoint(name="与合并无关的知识点")])
    knowledge_dedup_service.judge_article(
        db_session, primary, client=client, settings=build_settings(), now=NOW
    )

    relations = db_session.scalars(
        select(DuplicateRelation).where(DuplicateRelation.group_key == "group_t26")
    ).all()
    assert len(relations) == 2
    assert {row.is_primary for row in relations} == {True, False}
    assert primary.status is not ArticleStatus.KNOWLEDGE_DUPLICATE


def test_wiki_entry_status_is_respected(db_session: Session) -> None:
    """已废止条目不再作为覆盖依据。"""

    entry = entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    wiki_service.retire_entry(db_session, entry.id)
    article = make_article(db_session, url="https://a.example.com/retired")

    outcome = knowledge_dedup_service.judge_article(
        db_session,
        article,
        client=StaticLlmClient(
            points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR
        ),
        settings=build_settings(),
        now=NOW,
    )

    assert outcome.archived is False
    assert article.knowledge_status is KnowledgeStatus.NEW


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------


@pytest.fixture()
def knowledge_client(api_app: FastAPI) -> TestClient:
    client = StaticLlmClient(points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR)
    api_app.dependency_overrides[get_llm_client] = lambda: client
    # 接口走应用配置：这里显式开启知识级去重（默认关闭，避免生产误筛）
    api_app.dependency_overrides[get_settings] = lambda: build_settings()
    with TestClient(api_app) as test_client:
        yield test_client
    api_app.dependency_overrides.pop(get_llm_client, None)
    api_app.dependency_overrides.pop(get_settings, None)


def test_knowledge_admin_api(
    knowledge_client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    entry = entry_with_vector(api_session, "Raft 选主流程", VECTOR_A)
    article = make_article(api_session, url="https://a.example.com/api")

    run = knowledge_client.post(
        "/api/v1/admin/knowledge/run",
        headers=admin_headers,
        json={"article_ids": [article.id]},
    )
    assert run.status_code == 200
    assert run.json()["archived"] == 1

    decisions = knowledge_client.get(
        "/api/v1/admin/knowledge-decisions", headers=admin_headers, params={"decision": "covered"}
    )
    assert decisions.status_code == 200
    body = decisions.json()
    assert body["total"] == 1
    assert body["items"][0]["matched_entry_id"] == entry.id
    assert body["items"][0]["model"]

    bad_filter = knowledge_client.get(
        "/api/v1/admin/knowledge-decisions", headers=admin_headers, params={"decision": "unknown"}
    )
    assert bad_filter.status_code == 400

    override = knowledge_client.post(
        f"/api/v1/admin/articles/{article.id}/knowledge-override",
        headers=admin_headers,
        json={"decision": "new_knowledge", "reason": "包含实测数据"},
    )
    assert override.status_code == 200
    assert override.json()["actor"] == "human"

    stats = knowledge_client.get("/api/v1/admin/knowledge-stats", headers=admin_headers)
    assert stats.status_code == 200
    assert stats.json()["filtered_total"] == 0  # 改判后不再计入被筛
    assert stats.json()["llm_usage"]["calls_today"] >= 1

    missing = knowledge_client.post(
        "/api/v1/admin/articles/article_missing/knowledge-override",
        headers=admin_headers,
        json={"decision": "new_knowledge", "reason": "x"},
    )
    assert missing.status_code == 404

    assert api_session.scalar(select(func.count()).select_from(KnowledgeDecision)) == 2
    assert api_session.scalar(select(func.count()).select_from(WikiEntry)) == 1


def test_knowledge_endpoints_require_authorization(knowledge_client: TestClient) -> None:
    for method, path, payload in (
        ("get", "/api/v1/admin/knowledge-decisions", None),
        ("get", "/api/v1/admin/knowledge-stats", None),
        ("post", "/api/v1/admin/knowledge/run", {}),
        (
            "post",
            "/api/v1/admin/articles/article_x/knowledge-override",
            {"decision": "new_knowledge", "reason": "r"},
        ),
    ):
        call = getattr(knowledge_client, method)
        response = call(path, json=payload) if payload is not None else call(path)
        assert response.status_code in (401, 403), f"{method} {path} 未拒绝未授权访问"


def test_pipeline_judge_counts_archived(db_session: Session) -> None:
    """流水线钩子：文本级去重之后做知识级判定，并返回归档数量。"""

    entry_with_vector(db_session, "Raft 选主流程", VECTOR_A)
    article = make_article(db_session, url="https://a.example.com/pipeline")

    archived = knowledge_dedup_service.pipeline_judge(
        db_session,
        [article],
        client=StaticLlmClient(
            points=[KnowledgePoint(name="Raft 选主流程")], embedding=VECTOR_A_NEAR
        ),
        settings=build_settings(),
    )

    assert archived == 1
    assert article.status is ArticleStatus.KNOWLEDGE_DUPLICATE


def test_pipeline_judge_is_noop_when_disabled(db_session: Session) -> None:
    article = make_article(db_session, url="https://a.example.com/pipeline-off")

    archived = knowledge_dedup_service.pipeline_judge(
        db_session,
        [article],
        client=StaticLlmClient(points=[KnowledgePoint(name="知识点")]),
        settings=build_settings(knowledge_enabled=False),
    )

    assert archived == 0
    assert article.knowledge_status is None


def test_source_frequency_enum_untouched_by_knowledge_layer() -> None:
    """知识层不应影响既有调度档位语义（回归护栏）。"""

    assert UpdateFrequency.HIGH.value == "high"
    assert DigestStatus.SENT.value == "sent"
