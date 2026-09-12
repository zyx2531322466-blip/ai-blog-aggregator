"""知识点提炼缓存与用量统计（T25）。

把"调用外部模型"这件事收敛到一个可测试的入口：
- 同一篇文章只提炼一次（``knowledge_extractions`` 按文章唯一 + 内容指纹校验）；
- 调用失败（超时/限流/配额/非法输出）记录为 failed，不抛给上层中断流程；
- 记录 token 用量与尝试次数，支撑成本控制与"当日调用量/失败率"查询。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.base import utcnow
from app.db.enums import ExtractionStatus
from app.db.models import Article, KnowledgeExtraction
from app.dedup.fingerprint import content_fingerprint
from app.knowledge.llm_client import KnowledgePoint, LlmClient, LlmError


def article_fingerprint(article: Article) -> str:
    """文章内容指纹（用于"内容是否变化"的判断与缓存键）。"""

    return article.content_hash or content_fingerprint(f"{article.title}\n{article.content or ''}")


def get_extraction(session: Session, article_id: str) -> KnowledgeExtraction | None:
    """读取该文章的提炼记录（可能为空）。"""

    return session.scalars(
        select(KnowledgeExtraction).where(KnowledgeExtraction.article_id == article_id)
    ).first()


def points_from_row(row: KnowledgeExtraction) -> list[KnowledgePoint]:
    """把落库的 JSON 还原为知识点对象。"""

    points: list[KnowledgePoint] = []
    for item in row.points or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        claims = item.get("claims")
        points.append(
            KnowledgePoint(
                name=str(item["name"]),
                summary=str(item.get("summary") or ""),
                claims=[str(claim) for claim in claims] if isinstance(claims, list) else [],
            )
        )
    return points


def extract_points(
    session: Session,
    article: Article,
    *,
    client: LlmClient,
    settings: Settings | None = None,
    force: bool = False,
) -> KnowledgeExtraction:
    """提炼文章知识点（带缓存）；失败时记录状态并返回该记录，不抛异常。"""

    base = settings or get_settings()
    fingerprint = article_fingerprint(article)
    row = get_extraction(session, article.id)

    if row is not None and not force and row.status is ExtractionStatus.OK:
        if row.fingerprint == fingerprint:
            return row  # 缓存命中：同一内容不重复调用外部模型

    if row is None:
        row = KnowledgeExtraction(article_id=article.id, fingerprint=fingerprint)
        session.add(row)
        session.flush()

    row.fingerprint = fingerprint
    row.model = base.llm_model
    row.prompt_version = base.knowledge_prompt_version
    row.attempts += 1
    try:
        result = client.extract_points(title=article.title, content=article.content or "")
    except LlmError as exc:
        row.status = ExtractionStatus.FAILED
        row.error = str(exc)
        session.commit()
        session.refresh(row)
        return row
    except Exception as exc:  # noqa: BLE001 - 任何异常都不应中断采集/浏览/推送
        row.status = ExtractionStatus.FAILED
        row.error = f"未知错误：{exc}"
        session.commit()
        session.refresh(row)
        return row

    row.status = ExtractionStatus.OK
    row.points = [point.to_dict() for point in result.points]
    row.prompt_tokens += result.prompt_tokens
    row.completion_tokens += result.completion_tokens
    row.error = None
    session.commit()
    session.refresh(row)
    return row


def pending_articles(session: Session, *, limit: int = 50) -> list[Article]:
    """待判定（提炼未成功）的文章：后续轮次重试，不阻断主流程。"""

    rows = session.execute(
        select(Article)
        .join(KnowledgeExtraction, KnowledgeExtraction.article_id == Article.id)
        .where(KnowledgeExtraction.status != ExtractionStatus.OK)
        .limit(limit)
    ).all()
    return [row[0] for row in rows]


def usage_stats(session: Session, *, now: datetime | None = None) -> dict[str, object]:
    """当日调用量、失败数与 token 消耗（成本与配额视图）。"""

    moment = now or utcnow()
    start_of_day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = start_of_day - timedelta(0)

    calls = int(
        session.scalar(
            select(func.count())
            .select_from(KnowledgeExtraction)
            .where(KnowledgeExtraction.updated_at >= window_start)
        )
        or 0
    )
    failures = int(
        session.scalar(
            select(func.count())
            .select_from(KnowledgeExtraction)
            .where(
                KnowledgeExtraction.updated_at >= window_start,
                KnowledgeExtraction.status == ExtractionStatus.FAILED,
            )
        )
        or 0
    )
    tokens = int(
        session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        KnowledgeExtraction.prompt_tokens + KnowledgeExtraction.completion_tokens
                    ),
                    0,
                )
            ).where(KnowledgeExtraction.updated_at >= window_start)
        )
        or 0
    )
    total = int(session.scalar(select(func.count()).select_from(KnowledgeExtraction)) or 0)
    return {
        "calls_today": calls,
        "failures_today": failures,
        "tokens_today": tokens,
        "records_total": total,
    }
