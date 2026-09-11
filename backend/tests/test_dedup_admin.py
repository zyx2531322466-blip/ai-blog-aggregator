"""T15 去重策略管理与审计（命中记录、预览、变更记录、回滚）测试。"""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.enums import ArticleStatus, SourceListType
from app.db.models import Article, Source
from app.services import dedup_service, dedup_settings_service
from app.services.dedup_settings_service import DEFAULT_NEAR_DUPLICATE_THRESHOLD

BASE = (
    "昨天，某科技公司在一场发布会上正式推出了新一代人工智能模型。"
    "该模型在多项基准测试中取得了领先成绩，并支持更长的上下文。"
    "公司表示，新模型将在下个月面向开发者开放接口。"
    "业内专家认为，这次发布可能会改变现有的竞争格局。"
)
REPOST = (
    "昨天，某科技公司在一场发布会上正式推出了新一代人工智能模型。"
    "该模型在多项基准测试中取得了领先成绩，并支持更长的上下文。"
    "公司表示，新模型将在下个月面向开发者开放接口。"
    "业内专家认为，这次发布或将改变现有的竞争格局。"
)
REWRITE = (
    "某公司昨日发布了一款新的人工智能模型。"
    "据介绍，该模型在若干测试中表现优异，上下文长度也有所提升。"
    "开发者预计可以在下月获得接口。"
    "有分析人士指出，此举或许会重塑行业竞争态势。"
)

BASE_TIME = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
HISTORY_URL = "/api/v1/admin/dedup/history"
PREVIEW_URL = "/api/v1/admin/dedup/preview"
ROLLBACK_URL = "/api/v1/admin/dedup/rollback"
HITS_URL = "/api/v1/admin/dedup/hits"


def _seed_trio(session: Session) -> tuple[Article, Article, Article]:
    source = Source(
        name="站点A", site_url="https://a.example.com", list_type=SourceListType.WHITELIST
    )
    session.add(source)
    session.flush()

    def add(title: str, content: str, url: str, hours: int) -> Article:
        article = Article(
            title=title,
            content=content,
            url=url,
            source_id=source.id,
            status=ArticleStatus.NORMAL,
            created_at=BASE_TIME + timedelta(hours=hours),
            updated_at=BASE_TIME + timedelta(hours=hours),
        )
        session.add(article)
        session.flush()
        return article

    base = add("原新闻", BASE, "https://a.example.com/base", 0)
    repost = add("转载", REPOST, "https://b.example.com/repost", 1)
    rewrite = add("改写稿", REWRITE, "https://c.example.com/rewrite", 2)
    session.commit()

    dedup_service.process_article(session, base)
    dedup_service.process_article(session, repost)
    dedup_service.process_article(session, rewrite)
    return base, repost, rewrite


def _pairs(changes: list) -> set[frozenset[str]]:
    return {frozenset((item.article_id, item.other_article_id)) for item in changes}


# --- 变更记录与回滚 ---------------------------------------------------------------


def test_threshold_change_records_history(db_session: Session) -> None:
    dedup_settings_service.set_near_duplicate_threshold(db_session, 0.8, actor="alice")
    dedup_settings_service.set_near_duplicate_threshold(db_session, 0.7, actor="bob")

    history = dedup_settings_service.get_setting_history(db_session)
    assert len(history) == 2
    assert history[0].old_value == str(DEFAULT_NEAR_DUPLICATE_THRESHOLD)
    assert history[0].new_value == "0.8"
    assert history[0].actor == "alice"
    assert history[1].old_value == "0.8"
    assert history[1].new_value == "0.7"
    assert history[1].actor == "bob"


def test_rollback_restores_previous_value_and_records(db_session: Session) -> None:
    dedup_settings_service.set_near_duplicate_threshold(db_session, 0.8, actor="alice")
    dedup_settings_service.set_near_duplicate_threshold(db_session, 0.7, actor="bob")
    second = dedup_settings_service.get_setting_history(db_session)[1]

    restored = dedup_settings_service.rollback_setting(db_session, second.id, actor="carol")

    assert restored == 0.8
    assert dedup_settings_service.get_near_duplicate_threshold(db_session) == 0.8

    history = dedup_settings_service.get_setting_history(db_session)
    assert len(history) == 3
    assert history[-1].old_value == "0.7"
    assert history[-1].new_value == "0.8"
    assert history[-1].actor == "carol"


def test_rollback_unknown_history_is_rejected(db_session: Session) -> None:
    try:
        dedup_settings_service.rollback_setting(db_session, "dedup_history_missing", actor="carol")
    except ApiError as exc:
        assert exc.status_code == 404
    else:  # pragma: no cover - 失败路径
        raise AssertionError("不存在的变更记录应返回 404")


# --- 命中记录 -------------------------------------------------------------------


def test_relation_hits_include_type_evidence_and_sources(db_session: Session) -> None:
    _seed_trio(db_session)

    hits = dedup_service.list_relation_hits(db_session)
    by_type = {}
    for relation, target, member in hits:
        by_type.setdefault(relation.relation_type.value, []).append((relation, target, member))

    assert "near_duplicate" in by_type
    near_relation, near_target, near_member = by_type["near_duplicate"][0]
    assert near_relation.evidence
    assert near_target is not None and near_member is not None
    assert near_target.source.name == "站点A"
    assert near_member.url.startswith("https://b.example.com")
    # 关联推荐也被记录（不同视角，不合并）
    assert "related" in by_type


# --- 预览 -----------------------------------------------------------------------


def test_preview_reports_would_merge_and_would_unmerge(db_session: Session) -> None:
    base, repost, rewrite = _seed_trio(db_session)

    lower = dedup_service.preview_threshold_change(db_session, 0.6)
    assert lower.current_threshold == DEFAULT_NEAR_DUPLICATE_THRESHOLD
    assert lower.proposed_threshold == 0.6
    assert frozenset((base.id, rewrite.id)) in _pairs(lower.would_merge)

    higher = dedup_service.preview_threshold_change(db_session, 0.95)
    assert frozenset((base.id, repost.id)) in _pairs(higher.would_unmerge)


def test_preview_matches_applied_result(db_session: Session) -> None:
    base, repost, rewrite = _seed_trio(db_session)

    preview = dedup_service.preview_threshold_change(db_session, 0.6)
    proposed_merges = _pairs(preview.would_merge)
    assert proposed_merges  # 至少包含 (base, rewrite)

    # 应用新阈值并重新处理（主记录/成员幂等跳过）
    dedup_settings_service.set_near_duplicate_threshold(db_session, 0.6, actor="tester")
    for article in (base, repost, rewrite):
        dedup_service.process_article(db_session, article)

    for pair in proposed_merges:
        left_id, right_id = tuple(pair)
        left = db_session.get(Article, left_id)
        right = db_session.get(Article, right_id)
        assert dedup_service.resolve_primary(db_session, left).id == (
            dedup_service.resolve_primary(db_session, right).id
        )


# --- API 层 ---------------------------------------------------------------------


def test_admin_dedup_history_and_rollback_api(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    client.patch(
        "/api/v1/admin/dedup/settings",
        json={"near_duplicate_threshold": 0.8},
        headers=admin_headers,
    )
    client.patch(
        "/api/v1/admin/dedup/settings",
        json={"near_duplicate_threshold": 0.7},
        headers=admin_headers,
    )

    history = client.get(HISTORY_URL, headers=admin_headers).json()
    assert len(history) == 2
    assert history[1]["new_value"] == "0.7"
    assert history[1]["actor"]

    rolled = client.post(ROLLBACK_URL, json={"history_id": history[1]["id"]}, headers=admin_headers)
    assert rolled.status_code == 200
    assert rolled.json()["near_duplicate_threshold"] == 0.8


def test_admin_dedup_preview_and_hits_api(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    _seed_trio(api_session)

    preview = client.post(
        PREVIEW_URL, json={"near_duplicate_threshold": 0.6}, headers=admin_headers
    )
    assert preview.status_code == 200
    assert preview.json()["would_merge"]

    hits = client.get(HITS_URL, headers=admin_headers)
    assert hits.status_code == 200
    body = hits.json()
    assert body["total"] >= 2
    types = {item["relation_type"] for item in body["items"]}
    assert "near_duplicate" in types
    assert "related" in types
    sample = next(item for item in body["items"] if item["relation_type"] == "near_duplicate")
    assert sample["evidence"]
    assert sample["duplicate"]["source_name"] == "站点A"


def test_admin_dedup_endpoints_require_authorization(client: TestClient) -> None:
    assert client.get(HISTORY_URL).status_code == 401
    assert client.post(PREVIEW_URL, json={"near_duplicate_threshold": 0.6}).status_code == 401
    assert client.post(ROLLBACK_URL, json={"history_id": "x"}).status_code == 401
    assert client.get(HITS_URL).status_code == 401
