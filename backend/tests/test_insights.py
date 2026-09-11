"""T20 维护者效果概览接口测试。"""

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.enums import ArticleStatus, SourceListType
from app.db.models import Article, Source
from app.services import category_service, dedup_service

INSIGHTS_URL = "/api/v1/admin/insights"

BASE = (
    "昨天，某科技公司在一场发布会上正式推出了新一代人工智能模型。"
    "该模型在多项基准测试中取得了领先成绩，并支持更长的上下文。"
    "公司表示，新模型将在下个月面向开发者开放接口。"
    "业内专家认为，这次发布可能会改变现有的竞争格局。"
)
REACTION = (
    "针对某科技公司昨天发布的新一代人工智能模型，多家竞争对手今天作出了回应。"
    "有公司宣布将加快自家模型的迭代节奏，也有开发者担心价格与合规问题。"
)


def _build_dataset(session: Session) -> SimpleNamespace:
    category_service.ensure_default_categories(session)
    ai = category_service.find_category_by_name(session, "AI/机器学习")
    database = category_service.find_category_by_name(session, "数据库")

    source = Source(name="站点A", site_url="https://a.example", list_type=SourceListType.WHITELIST)
    session.add(source)
    session.flush()

    def add(
        title: str, content: str, url: str, category_id, status=ArticleStatus.NORMAL
    ) -> Article:
        article = Article(
            title=title,
            content=content,
            url=url,
            source_id=source.id,
            primary_category_id=category_id,
            status=status,
        )
        session.add(article)
        session.flush()
        return article

    original = add("原新闻", BASE, "https://a.example/1", ai.id)
    exact_copy = add("原新闻转载", BASE, "https://b.example/1", ai.id)
    related_view = add("行业反应", REACTION, "https://c.example/1", ai.id)
    add("SQL 优化", "数据库索引与事务的正文内容。", "https://a.example/2", database.id)
    uncategorized = add(
        "随手记事",
        "今天天气不错。",
        "https://a.example/3",
        None,
        status=ArticleStatus.UNCATEGORIZED,
    )
    add("广告", "立即购买，限时优惠。", "https://a.example/4", ai.id, status=ArticleStatus.FILTERED)
    session.commit()

    dedup_service.process_article(session, original)
    dedup_service.process_article(session, exact_copy)
    dedup_service.process_article(session, related_view)

    return SimpleNamespace(ai=ai, database=database, uncategorized=uncategorized)


def test_insights_matches_database_records(
    client: TestClient, admin_headers: dict[str, str], api_session: Session
) -> None:
    _build_dataset(api_session)

    response = client.get(INSIGHTS_URL, headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()

    distribution = body["category_distribution"]
    # 完全重复的成员不计入分类分布（只展示合并后的一条）
    assert distribution["AI/机器学习"] == 2
    assert distribution["数据库"] == 1
    assert distribution["未分类"] == 1
    assert distribution.get("安全", 0) == 0

    stats = body["dedup_stats"]
    assert stats["exact_duplicate"] == 1
    assert stats["near_duplicate"] == 0
    assert stats["related"] == 1
    assert stats["merged_duplicates"] == 1
    assert stats["total_articles"] == 5  # 已过滤的广告不计入
    assert stats["unique_articles"] == 4


def test_insights_requires_authorization(client: TestClient) -> None:
    response = client.get(INSIGHTS_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
