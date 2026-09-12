"""T23 摘要生成与邮件投递测试。

覆盖：方向匹配（类别/标签/来源/关键词与归一化）、条目组装（排除已推送、合并成员、知识重复、截断）、
幂等（同周期重跑、跨周期不重复推送同一篇）、模板渲染与转义、投递失败与重试、空周期策略。
全程使用记录型发送器，不触网、不发真实邮件。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import (
    ArticleStatus,
    CategoryStatus,
    DedupRelationType,
    DigestStatus,
    KnowledgeStatus,
    SubscriptionFrequency,
    SubscriptionStatus,
    SubscriptionTopicType,
)
from app.db.models import (
    Article,
    Category,
    DuplicateRelation,
    Digest,
    DigestItem,
    Source,
    Tag,
)
from app.core.config import Settings
from app.notifications.mailer import RecordingMailSender
from app.services import digest_service, subscription_service
from app.services.subscription_service import TopicInput

NOW = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)  # 周一


def build_settings(**overrides: object) -> Settings:
    """构造测试用配置（与 conftest 的约定一致，保持本模块自包含）。"""

    base: dict[str, object] = {
        "environment": "test",
        "admin_token": "test-admin-token",
        "admin_actor": "test-admin",
        "database_url": "sqlite+pysqlite:///:memory:",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def make_category(session: Session, name: str = "AI/机器学习") -> Category:
    category = Category(name=name, status=CategoryStatus.ACTIVE)
    session.add(category)
    session.commit()
    return category


def make_source(session: Session, name: str = "示例博客") -> Source:
    source = Source(name=name, site_url=f"https://{name}.example.com/", weight=2.0)
    session.add(source)
    session.commit()
    return source


def make_article(
    session: Session,
    *,
    title: str,
    url: str,
    source: Source | None = None,
    category: Category | None = None,
    tags: list[str] | None = None,
    summary: str = "摘要内容",
    status: ArticleStatus = ArticleStatus.NORMAL,
    knowledge_status: KnowledgeStatus | None = None,
    crawled_at: datetime | None = None,
    published_at: datetime | None = None,
) -> Article:
    article = Article(
        title=title,
        content="正文",
        summary=summary,
        url=url,
        source_id=source.id if source else None,
        primary_category_id=category.id if category else None,
        status=status,
        knowledge_status=knowledge_status,
        crawled_at=crawled_at or NOW,
        published_at=published_at,
    )
    if tags:
        for name in tags:
            tag = session.scalars(select(Tag).where(Tag.name == name)).first()
            if tag is None:
                tag = Tag(name=name)
                session.add(tag)
            article.tags.append(tag)
    session.add(article)
    session.commit()
    return article


def confirmed_subscription(
    session: Session,
    *,
    topics: list[TopicInput],
    frequency: str = "weekly",
    max_items: int = 10,
    email: str = "reader@example.com",
    created_at: datetime | None = None,
) -> tuple[object, str]:
    subscription, token = subscription_service.create_subscription(
        session, email=email, topics=topics, frequency=frequency, max_items=max_items
    )
    subscription_service.confirm_subscription(session, token)
    session.refresh(subscription)
    if created_at is not None:
        subscription.confirmed_at = created_at
        session.commit()
    return subscription, token


def test_period_bucket_is_week_and_day_scoped() -> None:
    """周期桶：每日按自然日、每周按 ISO 周（周一为起点）。"""

    day_start, day_end = digest_service.period_bucket(SubscriptionFrequency.DAILY, NOW)
    assert day_start == datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
    assert day_end - day_start == timedelta(days=1)

    week_start, week_end = digest_service.period_bucket(SubscriptionFrequency.WEEKLY, NOW)
    assert week_start == datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
    assert week_end - week_start == timedelta(days=7)


def test_keyword_matching_normalizes_fullwidth_and_case(db_session: Session) -> None:
    """关键词匹配做 NFKC 归一化（全角/半角、大小写）。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session,
        title="Ｋｕｂｅｒｎｅｔｅｓ 调度器解析",  # 全角
        url="https://a.example.com/1",
        source=source,
        category=category,
    )
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.KEYWORD, "kubernetes")]
    )

    entries = digest_service.collect_entries(db_session, subscription, now=NOW)

    assert len(entries) == 1
    assert entries[0].matched_topics == ["关键词：kubernetes"]


def test_matching_also_checks_summary(db_session: Session) -> None:
    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session,
        title="与关键词无关的标题",
        summary="正文摘要里提到了向量数据库",
        url="https://a.example.com/2",
        source=source,
        category=category,
    )
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.KEYWORD, "向量数据库")]
    )

    assert len(digest_service.collect_entries(db_session, subscription, now=NOW)) == 1


def test_entries_exclude_unmatched_merged_and_knowledge_duplicates(db_session: Session) -> None:
    """条目组装：只保留命中方向、非合并成员、非知识重复的文章。"""

    category = make_category(db_session)
    other_category = make_category(db_session, "运维")
    source = make_source(db_session)
    matched = make_article(
        db_session,
        title="命中",
        url="https://a.example.com/matched",
        source=source,
        category=category,
    )
    make_article(
        db_session,
        title="未命中",
        url="https://a.example.com/miss",
        source=source,
        category=other_category,
    )
    merged_member = make_article(
        db_session,
        title="转载",
        url="https://a.example.com/repost",
        source=source,
        category=category,
    )
    make_article(
        db_session,
        title="知识重复",
        url="https://a.example.com/covered",
        source=source,
        category=category,
        knowledge_status=KnowledgeStatus.COVERED,
    )
    make_article(
        db_session,
        title="待判定",
        url="https://a.example.com/pending",
        source=source,
        category=category,
        knowledge_status=KnowledgeStatus.PENDING,
    )
    make_article(
        db_session,
        title="已过滤",
        url="https://a.example.com/filtered",
        source=source,
        category=category,
        status=ArticleStatus.FILTERED,
    )
    # 把 merged_member 标为非主记录的合并成员
    db_session.add(
        DuplicateRelation(
            group_key="group_1",
            relation_type=DedupRelationType.EXACT_DUPLICATE,
            article_id=merged_member.id,
            target_article_id=None,
            is_primary=False,
        )
    )
    db_session.commit()

    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )
    entries = digest_service.collect_entries(db_session, subscription, now=NOW)

    assert [entry.article_id for entry in entries] == [matched.id]


def test_entries_respect_max_items_and_order_by_published_at(db_session: Session) -> None:
    category = make_category(db_session)
    source = make_source(db_session)
    for index in range(4):
        make_article(
            db_session,
            title=f"文章 {index}",
            url=f"https://a.example.com/{index}",
            source=source,
            category=category,
            published_at=NOW - timedelta(days=index),
        )

    subscription, _ = confirmed_subscription(
        db_session,
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
        max_items=2,
    )
    entries = digest_service.collect_entries(db_session, subscription, now=NOW)

    assert len(entries) == 2
    assert [entry.title for entry in entries] == ["文章 0", "文章 1"]  # 新的在前


def test_entries_ignore_content_not_in_current_period(db_session: Session) -> None:
    """只组装本周期（本周）内新增的内容，历史内容不会重复补发。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session,
        title="上周的文章",
        url="https://a.example.com/old",
        source=source,
        category=category,
        crawled_at=NOW - timedelta(days=8),
    )
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )

    assert digest_service.collect_entries(db_session, subscription, now=NOW) == []


def test_source_and_tag_topics_match(db_session: Session) -> None:
    category = make_category(db_session)
    source = make_source(db_session)
    by_source = make_article(
        db_session,
        title="来源命中",
        url="https://a.example.com/s",
        source=source,
        category=category,
    )
    other_source = make_source(db_session, "另一个站点")
    make_article(
        db_session,
        title="标签命中",
        url="https://a.example.com/t",
        source=other_source,
        category=category,
        tags=["Kubernetes"],
    )

    by_source_sub, _ = confirmed_subscription(
        db_session,
        topics=[TopicInput(SubscriptionTopicType.SOURCE, source.id)],
        email="by-source@example.com",
    )
    entries = digest_service.collect_entries(db_session, by_source_sub, now=NOW)
    assert [entry.article_id for entry in entries] == [by_source.id]
    assert entries[0].matched_topics == ["来源：示例博客"]

    by_tag_sub, _ = confirmed_subscription(
        db_session,
        topics=[TopicInput(SubscriptionTopicType.TAG, "Kubernetes")],
        email="by-tag@example.com",
    )
    entries = digest_service.collect_entries(db_session, by_tag_sub, now=NOW)
    assert [entry.title for entry in entries] == ["标签命中"]


def test_not_due_subscription_is_skipped(db_session: Session) -> None:
    """未到节奏时间不发送。"""

    make_category(db_session)
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )
    subscription.confirmed_at = NOW - timedelta(days=2)  # 每周节奏，尚未满 7 天
    db_session.commit()

    sender = RecordingMailSender()
    digest = digest_service.process_subscription(db_session, subscription, sender=sender, now=NOW)

    assert digest is None
    assert sender.messages == []


def test_empty_period_is_recorded_but_not_sent(db_session: Session) -> None:
    """无新增时不发邮件，但留下"跳过"记录（可被维护者看到）。"""

    make_category(db_session)
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )
    subscription.confirmed_at = NOW - timedelta(days=8)
    db_session.commit()

    sender = RecordingMailSender()
    digest = digest_service.process_subscription(db_session, subscription, sender=sender, now=NOW)

    assert digest is not None and digest.status is DigestStatus.SKIPPED_EMPTY
    assert sender.messages == []
    assert subscription.last_sent_at is None


def test_send_empty_setting_sends_notification(db_session: Session) -> None:
    """开启"空周期也发送"时，会发送一封无内容的提示邮件。"""

    make_category(db_session)
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )
    subscription.confirmed_at = NOW - timedelta(days=8)
    db_session.commit()

    settings = build_settings(digest_send_empty=True)
    sender = RecordingMailSender()
    digest = digest_service.process_subscription(
        db_session, subscription, sender=sender, settings=settings, now=NOW
    )

    assert digest is not None and digest.status is DigestStatus.SENT
    assert len(sender.messages) == 1
    assert "本周期没有新的相关内容" in sender.messages[0].text_body


def test_digest_is_sent_once_per_period_and_not_duplicated_across_runs(db_session: Session) -> None:
    """幂等：同一周期内重跑不会产生第二封邮件，条目也不会重复。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session,
        title="新内容",
        url="https://a.example.com/new",
        source=source,
        category=category,
    )
    subscription, _ = confirmed_subscription(
        db_session,
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
        frequency="daily",
    )
    subscription.confirmed_at = NOW - timedelta(days=1)
    db_session.commit()

    sender = RecordingMailSender()
    first = digest_service.process_subscription(db_session, subscription, sender=sender, now=NOW)
    second = digest_service.process_subscription(
        db_session, subscription, sender=sender, now=NOW + timedelta(minutes=5)
    )

    assert first is not None and first.status is DigestStatus.SENT
    assert second is not None and second.id == first.id  # 复用同一记录
    assert len(sender.messages) == 1  # 只发了一封
    assert db_session.scalar(select(func.count()).select_from(Digest)) == 1


def test_同一文章不会跨周期重复推送(db_session: Session) -> None:
    """跨周期：已经推送过的文章不会在下一期再次出现。"""

    category = make_category(db_session)
    source = make_source(db_session)
    article = make_article(
        db_session,
        title="第一期内容",
        url="https://a.example.com/1st",
        source=source,
        category=category,
    )
    subscription, _ = confirmed_subscription(
        db_session,
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
        frequency="daily",
    )
    subscription.confirmed_at = NOW - timedelta(days=1)
    db_session.commit()

    sender = RecordingMailSender()
    digest_service.process_subscription(db_session, subscription, sender=sender, now=NOW)
    assert len(sender.messages) == 1

    # 第二天：只要没有新文章，就不应重复推送第一篇
    tomorrow = NOW + timedelta(days=1)
    second = digest_service.process_subscription(
        db_session, subscription, sender=sender, now=tomorrow
    )

    assert second is not None and second.status is DigestStatus.SKIPPED_EMPTY
    assert len(sender.messages) == 1
    assert article.id in digest_service.already_digested_article_ids(db_session, subscription.id)


def test_merged_sources_hint_in_email(db_session: Session) -> None:
    """合并组内容在邮件里提示"另有 N 个来源转载"。"""

    category = make_category(db_session)
    primary_source = make_source(db_session, "主站")
    mirror_source = make_source(db_session, "镜像站")
    primary = make_article(
        db_session,
        title="被转载的内容",
        url="https://a.example.com/p",
        source=primary_source,
        category=category,
    )
    mirror = make_article(
        db_session,
        title="被转载的内容（镜像）",
        url="https://b.example.com/p",
        source=mirror_source,
        category=category,
    )
    for article, is_primary in ((primary, True), (mirror, False)):
        db_session.add(
            DuplicateRelation(
                group_key="group_9",
                relation_type=DedupRelationType.NEAR_DUPLICATE,
                article_id=article.id,
                is_primary=is_primary,
            )
        )
    db_session.commit()

    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )
    subscription.confirmed_at = NOW - timedelta(days=8)
    db_session.commit()
    sender = RecordingMailSender()
    digest_service.process_subscription(db_session, subscription, sender=sender, now=NOW)

    message = sender.last
    assert message is not None
    assert "另有 1 个来源转载" in message.text_body
    assert "另有 1 个来源转载" in (message.html_body or "")


def test_email_contains_links_and_escapes_title(db_session: Session) -> None:
    """邮件必须包含原文链接与退订入口；标题中的特殊字符不能破坏渲染。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session,
        title="危险标题 <script>alert(1)</script>",
        url="https://a.example.com/xss",
        source=source,
        category=category,
    )
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )
    subscription.confirmed_at = NOW - timedelta(days=8)
    db_session.commit()
    settings = build_settings(public_base_url="https://reader.example.com")
    sender = RecordingMailSender()
    digest_service.process_subscription(
        db_session, subscription, sender=sender, settings=settings, now=NOW
    )

    message = sender.last
    assert message is not None
    assert "https://a.example.com/xss" in message.text_body
    assert "https://reader.example.com/subscriptions/unsubscribe?token=" in message.text_body
    assert "<script>alert(1)</script>" not in (message.html_body or "")  # 已转义
    assert "&lt;script&gt;" in (message.html_body or "")


def test_failed_send_is_recorded_and_retried(db_session: Session) -> None:
    """投递失败被记录；重试成功后状态变为已发送。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session, title="内容", url="https://a.example.com/r", source=source, category=category
    )
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )

    subscription.confirmed_at = NOW - timedelta(days=8)
    db_session.commit()
    failing_sender = RecordingMailSender(fail_times=1)
    first = digest_service.process_subscription(
        db_session, subscription, sender=failing_sender, now=NOW
    )
    assert first is not None and first.status is DigestStatus.FAILED
    assert first.error is not None and first.retry_count == 1
    assert db_session.get(Digest, first.id).status is DigestStatus.FAILED

    # 同一周期内重跑 → 命中已有失败记录并重试
    working_sender = RecordingMailSender()
    retried = digest_service.process_subscription(
        db_session, subscription, sender=working_sender, now=NOW + timedelta(minutes=1)
    )
    assert retried is not None and retried.id == first.id
    assert retried.status is DigestStatus.SENT
    assert len(working_sender.messages) == 1
    assert retried.item_count == 1


def test_retry_stops_at_max_attempts(db_session: Session) -> None:
    """超过重试上限后不再尝试，失败记录保留供维护者查看。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session, title="内容", url="https://a.example.com/max", source=source, category=category
    )
    subscription, _ = confirmed_subscription(
        db_session, topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")]
    )
    settings = build_settings(digest_max_retries=1)
    subscription.confirmed_at = NOW - timedelta(days=8)
    db_session.commit()

    sender = RecordingMailSender(fail_times=10)
    first = digest_service.process_subscription(
        db_session, subscription, sender=sender, settings=settings, now=NOW
    )
    attempts_after_first = sender.attempts
    again = digest_service.process_subscription(
        db_session, subscription, sender=sender, settings=settings, now=NOW + timedelta(minutes=1)
    )

    assert first is not None and first.retry_count == 1
    assert again is not None and again.id == first.id
    assert again.retry_count == 1
    assert sender.attempts == attempts_after_first  # 未再尝试发送


def test_unconfirmed_and_unsubscribed_subscriptions_are_never_sent(db_session: Session) -> None:
    """未确认 / 已退订的订阅绝不推送。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session, title="内容", url="https://a.example.com/n", source=source, category=category
    )

    pending, pending_token = subscription_service.create_subscription(
        db_session,
        email="pending@example.com",
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
    )
    sender = RecordingMailSender()
    assert digest_service.process_subscription(db_session, pending, sender=sender, now=NOW) is None

    subscription, token = confirmed_subscription(
        db_session,
        email="u@example.com",
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
    )
    unsubscribe_token = "unsub-token-for-test"
    subscription.unsubscribe_token_hash = subscription_service.hash_token(unsubscribe_token)
    db_session.commit()
    subscription_service.unsubscribe(db_session, unsubscribe_token, scope="self")

    assert (
        digest_service.process_subscription(db_session, subscription, sender=sender, now=NOW)
        is None
    )
    assert sender.messages == []
    assert pending_token  # 确认凭证存在（未使用）


def test_run_digest_cycle_processes_confirmed_only(db_session: Session) -> None:
    """整轮处理只覆盖"已确认"订阅，并返回本轮记录。"""

    category = make_category(db_session)
    source = make_source(db_session)
    make_article(
        db_session,
        title="内容",
        url="https://a.example.com/cycle",
        source=source,
        category=category,
    )
    confirmed, _ = confirmed_subscription(
        db_session,
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
        frequency="daily",
    )
    confirmed.confirmed_at = NOW - timedelta(days=2)
    db_session.commit()
    subscription_service.create_subscription(
        db_session,
        email="still-pending@example.com",
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
    )

    sender = RecordingMailSender()
    results = digest_service.run_digest_cycle(db_session, sender=sender, now=NOW)

    assert [digest.subscription_id for digest in results] == [confirmed.id]
    assert len(sender.messages) == 1
    assert db_session.scalar(select(func.count()).select_from(DigestItem)) == 1
    assert (
        db_session.scalar(
            select(func.count()).select_from(Digest).where(Digest.status == DigestStatus.SENT)
        )
        == 1
    )


def test_subscription_status_guard_blocks_unsubscribed_state(db_session: Session) -> None:
    """状态为未确认时直接返回 None（不产生记录）。"""

    make_category(db_session)
    subscription, _ = subscription_service.create_subscription(
        db_session,
        email="guard@example.com",
        topics=[TopicInput(SubscriptionTopicType.CATEGORY, "AI/机器学习")],
    )
    subscription.status = SubscriptionStatus.PENDING_CONFIRMATION
    db_session.commit()

    assert (
        digest_service.process_subscription(
            db_session, subscription, sender=RecordingMailSender(), now=NOW
        )
        is None
    )
