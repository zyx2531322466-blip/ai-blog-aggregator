"""T08 内容分类与多标签打标测试。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classifier.rules import Classification, classify_text
from app.db.enums import ArticleStatus, CategoryStatus
from app.db.models import Article, Tag
from app.services import category_service, classifier_service


def make_article(session: Session, title: str, content: str, url: str = "https://x/1") -> Article:
    article = Article(title=title, content=content, url=url, status=ArticleStatus.PENDING)
    session.add(article)
    session.flush()
    return article


def seed_categories(session: Session) -> None:
    category_service.ensure_default_categories(session)


# --- 规则层 -------------------------------------------------------------------


def test_classify_text_picks_top_scoring_category() -> None:
    result = classify_text(
        "机器学习入门",
        "本文介绍神经网络与深度学习模型的训练方法。",
    )
    assert result.category_name == "AI/机器学习"
    assert "机器学习" in result.tags
    assert "深度学习" in result.tags


def test_classify_text_title_weights_more_than_body() -> None:
    result = classify_text("数据库索引优化", "顺便聊了一点人工智能。")
    assert result.category_name == "数据库"


def test_classify_text_returns_none_without_match() -> None:
    result = classify_text("今天天气不错", "适合出门散步。")
    assert result.category_name is None
    assert result.scores == {}


def test_classify_text_respects_allowed_categories() -> None:
    result = classify_text(
        "机器学习入门",
        "深度学习与神经网络",
        allowed_categories={"Web 开发"},
    )
    assert result.category_name is None


# --- 落库服务 -----------------------------------------------------------------


def test_classify_article_sets_one_primary_category_from_controlled_list(
    db_session: Session,
) -> None:
    seed_categories(db_session)
    article = make_article(
        db_session,
        "React 前端实践",
        "使用 React 与 TypeScript 构建前端界面，涉及 CSS 与组件交互。",
    )

    result = classifier_service.classify_article(db_session, article)

    assert result.category_id is not None
    active_names = {
        category.name
        for category in category_service.list_categories(db_session, include_inactive=False)
    }
    assert article.primary_category.name in active_names
    assert article.primary_category.name == "Web 开发"
    assert article.status is ArticleStatus.NORMAL


def test_classify_article_attaches_multiple_tags(db_session: Session) -> None:
    seed_categories(db_session)
    article = make_article(
        db_session,
        "用 Python 训练深度学习模型",
        "介绍神经网络训练流程与 Transformer 结构。",
    )

    result = classifier_service.classify_article(db_session, article)

    assert len(result.tags) >= 2
    assert "Python" in result.tags
    assert "深度学习" in result.tags
    assert {tag.name for tag in article.tags} == set(result.tags)


def test_classify_article_excludes_deactivated_categories(db_session: Session) -> None:
    seed_categories(db_session)
    ai_category = category_service.find_category_by_name(db_session, "AI/机器学习")
    category_service.set_category_status(
        db_session, ai_category.id, CategoryStatus.INACTIVE, actor="tester"
    )

    article = make_article(db_session, "机器学习入门", "神经网络与模型训练。")
    result = classifier_service.classify_article(db_session, article)

    assert result.category_id is None
    assert article.primary_category_id is None


def test_classify_article_without_match_keeps_pending(db_session: Session) -> None:
    seed_categories(db_session)
    article = make_article(db_session, "随手记事", "今天读了点闲书。")

    result = classifier_service.classify_article(db_session, article)

    assert result.category_id is None
    assert article.status is ArticleStatus.PENDING


def test_tags_are_reused_and_queryable(db_session: Session) -> None:
    seed_categories(db_session)
    first = make_article(db_session, "机器学习基础", "讲解训练与模型。", url="https://x/1")
    second = make_article(db_session, "深度学习进阶", "讲解神经网络与训练。", url="https://x/2")

    classifier_service.classify_article(db_session, first)
    classifier_service.classify_article(db_session, second)

    tags = db_session.scalars(select(Tag).where(Tag.name.in_(["机器学习", "深度学习"]))).all()
    assert len(tags) == 2  # 同名标签复用，不重复创建
    ml_tag = next(tag for tag in tags if tag.name == "机器学习")
    assert {article.id for article in ml_tag.articles} == {first.id, second.id}


def test_classify_pending_articles_batch(db_session: Session) -> None:
    seed_categories(db_session)
    make_article(db_session, "Docker 部署实践", "使用 Kubernetes 与容器编排。", url="https://x/1")
    make_article(db_session, "SQL 查询优化", "数据库索引与事务。", url="https://x/2")
    db_session.commit()

    results = classifier_service.classify_pending_articles(db_session)

    assert len(results) == 2
    assert all(result.category_id is not None for result in results)


def test_classifier_can_be_injected(db_session: Session) -> None:
    seed_categories(db_session)
    article = make_article(db_session, "任意标题", "任意正文")

    def fake_classifier(title: str, content: str, **_: object) -> Classification:
        return Classification(category_name="安全", tags=["安全"], scores={"安全": 99})

    result = classifier_service.classify_article(db_session, article, classifier=fake_classifier)

    assert article.primary_category.name == "安全"
    assert result.tags == ["安全"]
