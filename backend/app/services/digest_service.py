"""摘要生成与邮件投递服务（T23）。

职责边界（对应 `tickets.md` T23）：
- **方向匹配**：类别/标签/来源直接比对，关键词对标题+摘要做归一化（NFKC + 大小写）后包含匹配，并记录命中原因；
- **条目组装**：排除文本级合并成员、排除知识级"已覆盖/待判定"、排除已推送过，再排序与截断；
- **渲染与投递**：Jinja2 双版本模板（HTML + 纯文本）+ ``MailSender`` 抽象；
- **幂等**：以"周期桶"为唯一键（同周期重跑不会产生第二封邮件），
  并以"该订阅已推送过的文章集合"保证跨周期不重复推送同一篇内容。

定时触发（节奏、发送时间窗、退信暂停）由 T24 负责；本模块只实现"处理一个订阅"的确定性逻辑，
因此测试可以完全驱动它，不需要真实时钟、网络或邮件服务器。
"""

from __future__ import annotations

import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.base import utcnow
from app.db.enums import (
    ArticleStatus,
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
    Subscription,
    SubscriptionTopic,
    Tag,
    article_tags,
)
from app.notifications.mailer import MailMessage, MailSender
from app.services import subscription_service
from app.services.dedup_service import MERGE_TYPES

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
FREQUENCY_INTERVAL = {
    SubscriptionFrequency.DAILY: timedelta(days=1),
    SubscriptionFrequency.WEEKLY: timedelta(days=7),
}
FREQUENCY_LABEL = {
    SubscriptionFrequency.DAILY: "每日",
    SubscriptionFrequency.WEEKLY: "每周",
}
# 知识级去重（T26）判定为下列状态的文章不进入推送
_KNOWLEDGE_BLOCKED = (KnowledgeStatus.COVERED, KnowledgeStatus.PENDING)

_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "j2"), default_for_string=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass
class DigestEntry:
    """一封摘要邮件中的一条内容。"""

    article_id: str
    title: str
    summary: str
    url: str
    source_name: str
    published_at: datetime | None
    matched_topics: list[str] = field(default_factory=list)
    merged_sources_count: int = 1

    @property
    def published_label(self) -> str:
        """人类可读的发布时间（缺失时回退为"时间未知"）。"""

        if self.published_at is None:
            return "时间未知"
        return self.published_at.strftime("%Y-%m-%d %H:%M")


def normalize_text(value: str | None) -> str:
    """关键词匹配前的归一化：NFKC（全角/半角统一）+ 大小写折叠。"""

    return unicodedata.normalize("NFKC", value or "").casefold()


def _as_aware(moment: datetime, reference: datetime) -> datetime:
    """把数据库读回的无时区时间视为与参考时间同一时区（SQLite 会丢失 tzinfo）。"""

    if moment.tzinfo is None and reference.tzinfo is not None:
        return moment.replace(tzinfo=reference.tzinfo)
    if moment.tzinfo is not None and reference.tzinfo is None:
        return moment.replace(tzinfo=None)
    return moment


def period_bucket(frequency: SubscriptionFrequency, now: datetime) -> tuple[datetime, datetime]:
    """返回该节奏下 ``now`` 所属的"周期桶"（用于幂等，避免重跑产生第二封邮件）。

    - 每日：当天 00:00 ~ 次日 00:00
    - 每周：本周一 00:00 ~ 下周一 00:00（ISO 周）
    """

    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if frequency is SubscriptionFrequency.DAILY:
        return start_of_day, start_of_day + timedelta(days=1)
    monday = start_of_day - timedelta(days=start_of_day.weekday())
    return monday, monday + timedelta(days=7)


def is_due(subscription: Subscription, now: datetime) -> bool:
    """是否到达该订阅的推送时间（以"上次成功发送/确认时间 + 间隔"为准）。"""

    reference = subscription.last_sent_at or subscription.confirmed_at or subscription.created_at
    reference = _as_aware(reference, now)
    interval = FREQUENCY_INTERVAL[subscription.frequency]
    return now - reference >= interval


def match_article(
    article: Article,
    *,
    topic_type: SubscriptionTopicType,
    topic_value: str,
    category_name: str | None,
    tag_names: set[str],
) -> bool:
    """单个方向是否命中该文章。"""

    if topic_type is SubscriptionTopicType.CATEGORY:
        return bool(category_name) and category_name == topic_value
    if topic_type is SubscriptionTopicType.TAG:
        return topic_value in tag_names
    if topic_type is SubscriptionTopicType.SOURCE:
        return article.source_id == topic_value
    haystack = normalize_text(f"{article.title or ''}\n{article.summary or ''}")
    keyword = normalize_text(topic_value)
    return bool(keyword) and keyword in haystack


def already_digested_article_ids(session: Session, subscription_id: str) -> set[str]:
    """该订阅已经进入过推送（含待投递/失败待重试）的文章集合：保证不重复打扰。"""

    rows = session.execute(
        select(DigestItem.article_id)
        .join(Digest, Digest.id == DigestItem.digest_id)
        .where(Digest.subscription_id == subscription_id)
    ).all()
    return {row[0] for row in rows}


def _non_primary_member_ids():
    """被合并的（非主记录）文章：只推送主记录，避免同一内容重复出现。"""

    return select(DuplicateRelation.article_id).where(
        DuplicateRelation.is_primary.is_(False),
        DuplicateRelation.relation_type.in_(MERGE_TYPES),
    )


def collect_entries(
    session: Session, subscription: Subscription, *, now: datetime | None = None
) -> list[DigestEntry]:
    """组装本期条目：方向命中的新增内容，排除已推送、合并成员与知识重复。"""

    moment = now or utcnow()
    period_start, _ = period_bucket(subscription.frequency, moment)
    topics = subscription_service.subscription_topics(session, subscription)
    if not topics:
        return []

    sent_ids = already_digested_article_ids(session, subscription.id)

    statement = (
        select(Article)
        .where(
            Article.status.notin_((ArticleStatus.FILTERED, ArticleStatus.ERROR)),
            Article.status != ArticleStatus.KNOWLEDGE_DUPLICATE,
            Article.id.notin_(_non_primary_member_ids()),
            or_(
                Article.knowledge_status.is_(None),
                Article.knowledge_status.notin_(_KNOWLEDGE_BLOCKED),
            ),
            Article.crawled_at >= period_start,
        )
        .order_by(Article.crawled_at.desc())
    )

    entries: list[DigestEntry] = []
    for article in session.scalars(statement).all():
        if article.id in sent_ids:
            continue
        reasons = _matched_reasons(session, subscription, article, topics)
        if reasons:
            entries.append(_build_entry(session, article, reasons))

    entries.sort(
        key=lambda entry: _as_aware(entry.published_at, moment) if entry.published_at else moment,
        reverse=True,
    )
    return entries[: subscription.max_items]


def _matched_reasons(
    session: Session,
    subscription: Subscription,
    article: Article,
    topics: list[SubscriptionTopic],
) -> list[str]:
    category_name = _category_name(session, article)
    tag_names = _tag_names(session, article)
    reasons: list[str] = []
    for topic in topics:
        if match_article(
            article,
            topic_type=topic.topic_type,
            topic_value=topic.topic_value,
            category_name=category_name,
            tag_names=tag_names,
        ):
            reasons.append(_describe_topic(session, topic))
    return reasons


def _describe_topic(session: Session, topic: SubscriptionTopic) -> str:
    if topic.topic_type is SubscriptionTopicType.SOURCE:
        source = session.get(Source, topic.topic_value)
        return f"来源：{source.name if source else topic.topic_value}"
    if topic.topic_type is SubscriptionTopicType.CATEGORY:
        return f"类别：{topic.topic_value}"
    if topic.topic_type is SubscriptionTopicType.TAG:
        return f"标签：{topic.topic_value}"
    return f"关键词：{topic.topic_value}"


def _category_name(session: Session, article: Article) -> str | None:
    if not article.primary_category_id:
        return None
    category = session.get(Category, article.primary_category_id)
    return category.name if category else None


def _tag_names(session: Session, article: Article) -> set[str]:
    rows = session.execute(
        select(Tag.name)
        .join(article_tags, article_tags.c.tag_id == Tag.id)
        .where(article_tags.c.article_id == article.id)
    ).all()
    return {row[0] for row in rows}


def _merged_sources_count(session: Session, article: Article) -> int:
    """该内容在合并组内的来源数量（>1 时邮件里会提示"另有 N 个来源转载"）。"""

    rows = session.execute(
        select(DuplicateRelation.group_key).where(
            DuplicateRelation.article_id == article.id,
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).all()
    group_key = next((row[0] for row in rows if row[0]), None)
    if not group_key:
        return 1
    members = session.execute(
        select(DuplicateRelation.article_id).where(
            DuplicateRelation.group_key == group_key,
            DuplicateRelation.relation_type.in_(MERGE_TYPES),
        )
    ).all()
    return max(len({row[0] for row in members}), 1)


def _build_entry(session: Session, article: Article, reasons: list[str]) -> DigestEntry:
    source = session.get(Source, article.source_id) if article.source_id else None
    return DigestEntry(
        article_id=article.id,
        title=article.title,
        summary=article.summary or "",
        url=article.url,
        source_name=source.name if source else "未知来源",
        published_at=article.published_at,
        matched_topics=reasons,
        merged_sources_count=_merged_sources_count(session, article),
    )


def render_digest(
    session: Session,
    subscription: Subscription,
    entries: list[DigestEntry],
    *,
    unsubscribe_token: str,
    settings: Settings,
    now: datetime,
) -> MailMessage:
    """渲染摘要邮件（HTML 与纯文本双版本）。"""

    topics = [
        _describe_topic(session, topic)
        for topic in subscription_service.subscription_topics(session, subscription)
    ]
    period_start, period_end = period_bucket(subscription.frequency, now)
    context = {
        "subscription_email_masked": subscription_service.mask_email(subscription.email),
        "period_label": (
            f"{period_start:%Y-%m-%d} ~ {period_end - timedelta(days=1):%Y-%m-%d} "
            f"（{FREQUENCY_LABEL[subscription.frequency]}）"
        ),
        "items": entries,
        "topics": topics,
        "unsubscribe_link": subscription_service.build_unsubscribe_link(
            settings, unsubscribe_token
        ),
        "settings_note": "本邮件由自动推送生成，请勿直接回复。",
    }
    text_body = _ENV.get_template("digest_email.txt.j2").render(**context)
    html_body = _ENV.get_template("digest_email.html.j2").render(**context)
    return MailMessage(
        to=subscription.email,
        subject=_subject(subscription, entries, period_start),
        text_body=text_body,
        html_body=html_body,
    )


def _subject(subscription: Subscription, entries: list[DigestEntry], period_start: datetime) -> str:
    label = FREQUENCY_LABEL[subscription.frequency]
    if entries:
        return f"[{label}摘要] {period_start:%m-%d} 起 {len(entries)} 篇新内容"
    return f"[{label}摘要] 本周期无新内容"


def _existing_digest(
    session: Session, subscription_id: str, period_start: datetime, period_end: datetime
) -> Digest | None:
    return session.scalars(
        select(Digest).where(
            Digest.subscription_id == subscription_id,
            Digest.period_start == period_start,
            Digest.period_end == period_end,
        )
    ).first()


def _rotate_unsubscribe_token(session: Session, subscription: Subscription) -> str:
    """为本次邮件生成新的退订凭证（只存哈希）。

    退订凭证随每封邮件轮换：邮件里始终携带最新可用链接，而数据库始终不保存明文凭证。
    """

    token = secrets.token_urlsafe(32)
    subscription.unsubscribe_token_hash = subscription_service.hash_token(token)
    session.flush()
    return token


def _deliver(
    session: Session,
    subscription: Subscription,
    digest: Digest,
    entries: list[DigestEntry],
    *,
    sender: MailSender,
    settings: Settings,
    now: datetime,
) -> None:
    """渲染并投递；成功置为 sent，失败记录原因并留待重试。"""

    token = _rotate_unsubscribe_token(session, subscription)
    message = render_digest(
        session, subscription, entries, unsubscribe_token=token, settings=settings, now=now
    )
    try:
        sender.send(message)
    except Exception as exc:  # noqa: BLE001 - 投递失败必须记录，不能让整轮中断
        digest.status = DigestStatus.FAILED
        digest.error = str(exc)
        digest.retry_count += 1
        session.commit()
        return

    digest.status = DigestStatus.SENT
    digest.sent_at = now
    digest.error = None
    subscription.last_sent_at = now
    session.commit()


def process_subscription(
    session: Session,
    subscription: Subscription,
    *,
    sender: MailSender,
    settings: Settings | None = None,
    now: datetime | None = None,
    force: bool = False,
) -> Digest | None:
    """处理单个订阅：返回本次的推送记录；未到时间或本周期已处理则返回已有记录 / None。"""

    settings = settings or get_settings()
    moment = now or utcnow()
    if subscription.status is not SubscriptionStatus.CONFIRMED:
        return None  # 未确认 / 已退订：绝不推送

    period_start, period_end = period_bucket(subscription.frequency, moment)
    existing = _existing_digest(session, subscription.id, period_start, period_end)

    if existing is not None:
        if existing.status is not DigestStatus.FAILED:
            return existing  # 幂等：本周期已处理（含"空周期跳过"）
        if existing.retry_count >= settings.digest_max_retries:
            return existing  # 重试次数用尽：保留失败记录供维护者查看
        # 失败重试：沿用该记录已入库的条目（重新收集会把它们当成"已推送过"而漏掉）
        entries = entries_for_digest(session, existing)
        existing.item_count = len(entries)
        _deliver(
            session, subscription, existing, entries, sender=sender, settings=settings, now=moment
        )
        session.refresh(existing)
        return existing

    if not force and not is_due(subscription, moment):
        return None

    entries = collect_entries(session, subscription, now=moment)

    if existing is None:
        digest = Digest(
            subscription_id=subscription.id,
            period_start=period_start,
            period_end=period_end,
            status=DigestStatus.PENDING,
            item_count=len(entries),
        )
        session.add(digest)
        session.flush()
        for position, entry in enumerate(entries, start=1):
            session.add(
                DigestItem(
                    digest_id=digest.id,
                    article_id=entry.article_id,
                    position=position,
                    matched_topics=entry.matched_topics,
                )
            )
        session.commit()
    else:
        digest = existing
        digest.item_count = len(entries)

    if not entries and not settings.digest_send_empty:
        digest.status = DigestStatus.SKIPPED_EMPTY
        session.commit()
        return digest

    _deliver(session, subscription, digest, entries, sender=sender, settings=settings, now=moment)
    session.refresh(digest)
    return digest


def entries_for_digest(session: Session, digest: Digest) -> list[DigestEntry]:
    """由已落库的推送条目还原渲染所需数据（用于失败重试）。"""

    rows = session.scalars(
        select(DigestItem).where(DigestItem.digest_id == digest.id).order_by(DigestItem.position)
    ).all()
    entries: list[DigestEntry] = []
    for row in rows:
        article = session.get(Article, row.article_id)
        if article is None:  # pragma: no cover - 文章被删除时跳过
            continue
        entries.append(_build_entry(session, article, list(row.matched_topics or [])))
    return entries


def run_digest_cycle(
    session: Session,
    *,
    sender: MailSender,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> list[Digest]:
    """对全部已确认订阅执行一轮处理，返回本轮涉及（生成 / 跳过 / 重试）的推送记录。"""

    settings = settings or get_settings()
    moment = now or utcnow()
    subscriptions = session.scalars(
        select(Subscription).where(Subscription.status == SubscriptionStatus.CONFIRMED)
    ).all()

    results: list[Digest] = []
    for subscription in subscriptions:
        digest = process_subscription(
            session, subscription, sender=sender, settings=settings, now=moment
        )
        if digest is not None:
            results.append(digest)
    return results


def digest_entries_view(session: Session, digest: Digest) -> list[dict[str, object]]:
    """把推送条目整理成接口返回结构（供 T24 的维护者接口使用）。"""

    rows = session.scalars(
        select(DigestItem).where(DigestItem.digest_id == digest.id).order_by(DigestItem.position)
    ).all()
    view: list[dict[str, object]] = []
    for row in rows:
        article = session.get(Article, row.article_id)
        view.append(
            {
                "article_id": row.article_id,
                "position": row.position,
                "matched_topics": list(row.matched_topics or []),
                "title": article.title if article else "",
                "url": article.url if article else "",
            }
        )
    return view
