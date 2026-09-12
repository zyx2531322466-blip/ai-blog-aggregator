"""T02 数据模型与存储层单元测试。

覆盖：
- 每张表至少一条增删改查（CRUD）用例
- 枚举以英文值落库、JSON 字段往返
- 数据结构不含任何用户账户/登录相关字段
"""

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.db.enums import (
    ArticleStatus,
    CategoryAction,
    CategoryStatus,
    DedupRelationType,
    SourceListType,
    UpdateFrequency,
)
from app.db.models import (
    Article,
    Category,
    CategoryHistory,
    DuplicateRelation,
    Source,
    Tag,
    article_tags,
)
from app.db.repository import Repository


def _make_source(session: Session, **overrides: object) -> Source:
    defaults: dict[str, object] = {
        "name": "示例博客",
        "site_url": "https://example.com",
        "focus_area_name": "AI",
        "focus_area_description": "人工智能相关",
        "keywords": ["机器学习", "神经网络"],
        "exclude_keywords": ["广告"],
        "example_urls": ["https://example.com/post/1"],
        "counter_example_urls": ["https://example.com/ad"],
    }
    defaults.update(overrides)
    source = Source(**defaults)  # type: ignore[arg-type]
    session.add(source)
    session.flush()
    return source


def _make_article(session: Session, source: Source, **overrides: object) -> Article:
    defaults: dict[str, object] = {
        "title": "一篇关于机器学习的文章",
        "content": "正文内容" * 10,
        "url": "https://example.com/post/1",
        "source_id": source.id,
    }
    defaults.update(overrides)
    article = Article(**defaults)  # type: ignore[arg-type]
    session.add(article)
    session.flush()
    return article


def test_source_create_read_update_delete(db_session: Session) -> None:
    repo = Repository(db_session, Source)
    source = _make_source(db_session)
    repo.commit()

    fetched = repo.get(source.id)
    assert fetched is not None
    assert fetched.list_type is SourceListType.WHITELIST
    assert fetched.weight == 1.0
    assert fetched.update_frequency is UpdateFrequency.NORMAL
    assert fetched.keywords == ["机器学习", "神经网络"]

    fetched.weight = 3.5
    fetched.update_frequency = UpdateFrequency.HIGH
    repo.commit()
    assert repo.get(source.id).weight == 3.5

    repo.delete(fetched)
    repo.commit()
    assert repo.get(source.id) is None


def test_source_blacklist_and_weight_defaults(db_session: Session) -> None:
    black = _make_source(
        db_session, site_url="https://spam.example", list_type=SourceListType.BLACKLIST
    )
    white = _make_source(db_session, site_url="https://good.example")
    db_session.commit()

    assert black.list_type is SourceListType.BLACKLIST
    # 新增来源默认权重相等
    assert black.weight == white.weight == 1.0


def test_category_and_history_crud(db_session: Session) -> None:
    repo = Repository(db_session, Category)
    category = Category(name="技术", is_default=True)
    db_session.add(category)
    db_session.flush()

    history = CategoryHistory(
        category_id=category.id,
        action=CategoryAction.CREATE,
        new_name="技术",
        actor="admin",
    )
    db_session.add(history)
    db_session.commit()

    assert repo.get(category.id).name == "技术"
    assert repo.get(category.id).status is CategoryStatus.ACTIVE

    category.name = "技术/工程"
    db_session.add(
        CategoryHistory(
            category_id=category.id,
            action=CategoryAction.RENAME,
            old_name="技术",
            new_name="技术/工程",
        )
    )
    db_session.commit()
    assert repo.get(category.id).name == "技术/工程"
    assert len(repo.get(category.id).history) == 2

    repo.delete(category)
    db_session.commit()
    assert repo.get(category.id) is None
    # 类别删除后历史保留（category_id 置空，便于追溯）
    remaining = db_session.scalars(select(CategoryHistory)).all()
    assert len(remaining) == 2
    assert all(row.category_id is None for row in remaining)


def test_tag_and_article_tags_crud(db_session: Session) -> None:
    source = _make_source(db_session)
    article = _make_article(db_session, source)
    tag_repo = Repository(db_session, Tag)

    tag = Tag(name="深度学习")
    db_session.add(tag)
    db_session.flush()
    article.tags.append(tag)
    db_session.commit()

    assert tag_repo.get(tag.id).name == "深度学习"
    assert [t.name for t in article.tags] == ["深度学习"]
    # 关联表可查询
    links = db_session.execute(select(article_tags)).all()
    assert len(links) == 1

    article.tags.remove(tag)
    db_session.commit()
    assert db_session.execute(select(article_tags)).all() == []

    tag_repo.delete(tag_repo.get(tag.id))
    db_session.commit()
    assert tag_repo.get(tag.id) is None


def test_article_crud_and_enum_persistence(db_session: Session) -> None:
    source = _make_source(db_session)
    category = Category(name="技术")
    db_session.add(category)
    db_session.flush()

    repo = Repository(db_session, Article)
    article = _make_article(
        db_session,
        source,
        primary_category_id=category.id,
        status=ArticleStatus.NORMAL,
        content_hash="a" * 64,
        simhash=123456789,
    )
    repo.commit()

    fetched = repo.get(article.id)
    assert fetched.title == "一篇关于机器学习的文章"
    assert fetched.status is ArticleStatus.NORMAL
    assert fetched.source.id == source.id
    assert fetched.primary_category.name == "技术"
    # 枚举以英文值（而非成员名）落库
    raw_status = db_session.execute(
        text("select status from articles where id = :id"), {"id": article.id}
    ).scalar_one()
    assert raw_status == "normal"

    fetched.title = "更新后的标题"
    repo.commit()
    assert repo.get(article.id).title == "更新后的标题"

    repo.delete(fetched)
    repo.commit()
    assert repo.get(article.id) is None


def test_article_list_filters(db_session: Session) -> None:
    source = _make_source(db_session)
    _make_article(db_session, source, url="https://example.com/a", status=ArticleStatus.NORMAL)
    _make_article(
        db_session,
        source,
        url="https://example.com/b",
        status=ArticleStatus.UNCATEGORIZED,
    )
    db_session.commit()

    repo = Repository(db_session, Article)
    assert len(repo.list()) == 2
    assert len(repo.list(status=ArticleStatus.NORMAL)) == 1
    assert repo.list(status=ArticleStatus.NORMAL)[0].url == "https://example.com/a"


def test_duplicate_relation_crud(db_session: Session) -> None:
    source = _make_source(db_session)
    primary = _make_article(db_session, source, url="https://example.com/a")
    duplicate = _make_article(db_session, source, url="https://example.com/b")
    db_session.commit()

    repo = Repository(db_session, DuplicateRelation)
    relation = DuplicateRelation(
        group_key="group_1",
        relation_type=DedupRelationType.EXACT_DUPLICATE,
        article_id=duplicate.id,
        target_article_id=primary.id,
        is_primary=False,
        similarity=1.0,
        evidence="content_hash 相同",
    )
    repo.add(relation)
    repo.commit()

    fetched = repo.get(relation.id)
    assert fetched.relation_type is DedupRelationType.EXACT_DUPLICATE
    assert fetched.target_article.id == primary.id

    fetched.relation_type = DedupRelationType.NEAR_DUPLICATE
    fetched.similarity = 0.97
    repo.commit()
    assert repo.get(relation.id).relation_type is DedupRelationType.NEAR_DUPLICATE

    # related 关系：不同视角，不合并
    related = DuplicateRelation(
        relation_type=DedupRelationType.RELATED,
        article_id=primary.id,
        target_article_id=duplicate.id,
    )
    repo.add(related)
    repo.commit()
    assert len(repo.list(relation_type=DedupRelationType.RELATED)) == 1

    repo.delete(fetched)
    repo.commit()
    assert repo.get(relation.id) is None


def test_schema_contains_no_user_account_fields(engine) -> None:
    """T02 明确要求：不含任何用户账户/登录相关字段。"""

    inspector = inspect(engine)
    forbidden_table_names = {"users", "user", "accounts", "account", "sessions", "credentials"}
    tables = set(inspector.get_table_names())
    assert tables.isdisjoint(forbidden_table_names)

    forbidden_column_hints = ("password", "passwd", "username", "login", "credential")
    for table in tables:
        for column in inspector.get_columns(table):
            name = column["name"].lower()
            assert not any(
                hint in name for hint in forbidden_column_hints
            ), f"{table}.{name} 疑似用户账户字段"
            # v2（T22）允许"匿名订阅"保存邮箱作为触达地址：它不是账号——
            # 没有注册/登录/密码/会话，身份仅由邮箱与一次性凭证表示。
            if "email" in name:
                assert table == "subscriptions", f"{table}.{name} 疑似用户账户字段"


def test_expected_tables_exist(engine) -> None:
    inspector = inspect(engine)
    assert {
        "articles",
        "categories",
        "category_history",
        "tags",
        "article_tags",
        "sources",
        "duplicate_relations",
    }.issubset(set(inspector.get_table_names()))
