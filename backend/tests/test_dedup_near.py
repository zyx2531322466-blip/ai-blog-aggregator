"""T13 近重复（转载/镜像/微改写）识别与阈值配置测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.enums import ArticleStatus, DedupRelationType, SourceListType
from app.db.models import Article, DuplicateRelation, Source
from app.dedup.simhash import compute_simhash, from_signed64, simhash_similarity, to_signed64
from app.services import dedup_service, dedup_settings_service
from app.services.dedup_settings_service import DEFAULT_NEAR_DUPLICATE_THRESHOLD

SETTINGS_URL = "/api/v1/admin/dedup/settings"

BASE = (
    "昨天，某科技公司在一场发布会上正式推出了新一代人工智能模型。"
    "该模型在多项基准测试中取得了领先成绩，并支持更长的上下文。"
    "公司表示，新模型将在下个月面向开发者开放接口。"
    "业内专家认为，这次发布可能会改变现有的竞争格局。"
)
# 转载/微改写：仅个别词不同
REPOST = (
    "昨天，某科技公司在一场发布会上正式推出了新一代人工智能模型。"
    "该模型在多项基准测试中取得了领先成绩，并支持更长的上下文。"
    "公司表示，新模型将在下个月面向开发者开放接口。"
    "业内专家认为，这次发布或将改变现有的竞争格局。"
)
# 主题相关但改写幅度较大、证据不充分
REWRITE = (
    "某公司昨日发布了一款新的人工智能模型。"
    "据介绍，该模型在若干测试中表现优异，上下文长度也有所提升。"
    "开发者预计可以在下月获得接口。"
    "有分析人士指出，此举或许会重塑行业竞争态势。"
)
UNRELATED = (
    "本文介绍了如何使用 Postgres 的索引优化慢查询，并给出了几个实际案例。"
    "同时讨论了事务隔离级别对并发性能的影响。"
)

BASE_TIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def make_source(session: Session) -> Source:
    source = Source(
        name="站点A", site_url="https://a.example.com", list_type=SourceListType.WHITELIST
    )
    session.add(source)
    session.flush()
    return source


def make_article(
    session: Session, source: Source, *, title: str, content: str, url: str, created_at: datetime
) -> Article:
    article = Article(
        title=title,
        content=content,
        url=url,
        source_id=source.id,
        status=ArticleStatus.NORMAL,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(article)
    session.flush()
    return article


def test_simhash_similarity_orders_samples() -> None:
    base_hash = compute_simhash(BASE)

    repost_similarity = simhash_similarity(base_hash, compute_simhash(REPOST))
    rewrite_similarity = simhash_similarity(base_hash, compute_simhash(REWRITE))
    unrelated_similarity = simhash_similarity(base_hash, compute_simhash(UNRELATED))

    assert repost_similarity > rewrite_similarity > unrelated_similarity
    assert repost_similarity >= DEFAULT_NEAR_DUPLICATE_THRESHOLD
    assert rewrite_similarity < DEFAULT_NEAR_DUPLICATE_THRESHOLD


def test_signed64_round_trip() -> None:
    for value in (0, 1, 2**63, 2**64 - 1):
        assert from_signed64(to_signed64(value)) == value


def test_default_threshold_merges_repost(db_session: Session) -> None:
    source = make_source(db_session)
    base = make_article(
        db_session,
        source,
        title="原新闻",
        content=BASE,
        url="https://a.example.com/1",
        created_at=BASE_TIME,
    )
    repost = make_article(
        db_session,
        source,
        title="转载",
        content=REPOST,
        url="https://b.example.com/1",
        created_at=BASE_TIME + timedelta(hours=1),
    )

    assert dedup_service.process_article(db_session, base).is_duplicate is False
    outcome = dedup_service.process_article(db_session, repost)

    assert outcome.is_duplicate is True
    assert outcome.relation is not None
    assert outcome.relation.relation_type is DedupRelationType.NEAR_DUPLICATE
    assert outcome.similarity is not None and outcome.similarity >= DEFAULT_NEAR_DUPLICATE_THRESHOLD
    assert repost.simhash is not None


def test_default_threshold_does_not_merge_insufficient_evidence(db_session: Session) -> None:
    source = make_source(db_session)
    base = make_article(
        db_session,
        source,
        title="原新闻",
        content=BASE,
        url="https://a.example.com/1",
        created_at=BASE_TIME,
    )
    rewrite = make_article(
        db_session,
        source,
        title="改写稿",
        content=REWRITE,
        url="https://b.example.com/1",
        created_at=BASE_TIME + timedelta(hours=1),
    )

    dedup_service.process_article(db_session, base)
    outcome = dedup_service.process_article(db_session, rewrite)

    assert outcome.is_duplicate is False
    assert outcome.similarity is not None
    assert outcome.similarity < DEFAULT_NEAR_DUPLICATE_THRESHOLD
    # 默认（保守）阈值下不会被误合并为重复；T14 会将其登记为"关联推荐"
    merge_relations = db_session.scalars(
        select(DuplicateRelation).where(
            DuplicateRelation.relation_type.in_(
                (DedupRelationType.EXACT_DUPLICATE, DedupRelationType.NEAR_DUPLICATE)
            )
        )
    ).all()
    assert merge_relations == []


def test_threshold_change_changes_judgement(db_session: Session) -> None:
    source = make_source(db_session)
    base = make_article(
        db_session,
        source,
        title="原新闻",
        content=BASE,
        url="https://a.example.com/1",
        created_at=BASE_TIME,
    )
    rewrite = make_article(
        db_session,
        source,
        title="改写稿",
        content=REWRITE,
        url="https://b.example.com/1",
        created_at=BASE_TIME + timedelta(hours=1),
    )
    unrelated = make_article(
        db_session,
        source,
        title="无关文章",
        content=UNRELATED,
        url="https://c.example.com/1",
        created_at=BASE_TIME + timedelta(hours=2),
    )

    dedup_service.process_article(db_session, base)
    assert dedup_service.process_article(db_session, rewrite).is_duplicate is False

    # 调低阈值（更激进）后，同一组样本被判定为近重复
    dedup_settings_service.set_near_duplicate_threshold(db_session, 0.6)
    outcome = dedup_service.process_article(db_session, rewrite)
    assert outcome.is_duplicate is True
    assert outcome.relation.relation_type is DedupRelationType.NEAR_DUPLICATE

    # 即便在 0.6 阈值下，明显不相关的内容仍不会被误合并
    assert dedup_service.process_article(db_session, unrelated).is_duplicate is False


def test_threshold_default_and_persistence(db_session: Session) -> None:
    assert (
        dedup_settings_service.get_near_duplicate_threshold(db_session)
        == DEFAULT_NEAR_DUPLICATE_THRESHOLD
    )

    dedup_settings_service.set_near_duplicate_threshold(db_session, 0.75)

    assert dedup_settings_service.get_near_duplicate_threshold(db_session) == 0.75


def test_invalid_threshold_rejected(db_session: Session) -> None:
    with pytest.raises(ApiError) as exc_info:
        dedup_settings_service.set_near_duplicate_threshold(db_session, 1.5)
    assert exc_info.value.status_code == 422


def test_settings_endpoint_get_and_patch(client: TestClient, admin_headers: dict[str, str]) -> None:
    default = client.get(SETTINGS_URL, headers=admin_headers)
    assert default.status_code == 200
    assert default.json()["near_duplicate_threshold"] == DEFAULT_NEAR_DUPLICATE_THRESHOLD

    patched = client.patch(
        SETTINGS_URL, json={"near_duplicate_threshold": 0.6}, headers=admin_headers
    )
    assert patched.status_code == 200
    assert patched.json()["near_duplicate_threshold"] == 0.6

    assert client.get(SETTINGS_URL, headers=admin_headers).json()["near_duplicate_threshold"] == 0.6


def test_settings_endpoints_require_authorization(client: TestClient) -> None:
    assert client.get(SETTINGS_URL).status_code == 401
    patched = client.patch(SETTINGS_URL, json={"near_duplicate_threshold": 0.6})
    assert patched.status_code == 401
    assert patched.json()["error"]["code"] == "UNAUTHORIZED"


def test_invalid_threshold_via_api_is_rejected(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.patch(
        SETTINGS_URL, json={"near_duplicate_threshold": 1.5}, headers=admin_headers
    )
    assert response.status_code == 422
