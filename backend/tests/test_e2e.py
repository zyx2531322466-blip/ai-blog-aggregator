"""T21 端到端集成验收。

覆盖"配置主题/来源 → 抓取 → 解析 → 过滤 → 分类/标签 → 去重（三类判定）→
主记录选择 → 查询展示 → 维护者管理"全链路，以及 spec 用户故事 1-9 的核心路径。

七类端到端场景：
1. 正常采集展示
2. 完全重复合并
3. 近重复合并
4. 不同视角不合并且关联
5. 未分类兜底与重新归类
6. 主记录切换
7. 阈值调整审计
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services import category_service, scheduler_service
from tests.fakes import StaticFetcher, load_fixture

FIXED_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
SITE_A = "https://a.example/"
SITE_B = "https://b.example/"
SPAM = "https://spam.example/"

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
REACTION = (
    "针对某科技公司昨天发布的新一代人工智能模型，多家竞争对手今天作出了回应。"
    "有公司宣布将加快自家模型的迭代节奏，也有开发者担心价格与合规问题。"
)
OFF_TOPIC = "今天读了点闲书，随手记录一下最近的心情与琐事。"


def _article_html(title: str, body: str) -> str:
    paragraphs = "".join(f"<p>{sentence}</p>" for sentence in body.split("。") if sentence)
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1>{paragraphs}</article></body></html>"
    )


def _index_html(links: list[str]) -> str:
    anchors = "".join(f'<a href="{url}">查看全文详情</a>' for url in links)
    return f"<html><head><title>文章目录</title></head><body><main>{anchors}</main></body></html>"


def _create_source(
    client: TestClient, headers: dict, name: str, site: str, *, weight=None, list_type="whitelist"
):
    payload = {
        "name": name,
        "site_url": site,
        "list_type": list_type,
    }
    if list_type == "whitelist":
        payload.update(
            {
                "focus_area_name": name,
                "focus_area_description": "端到端测试领域",
                "keywords": ["测试"],
                "example_urls": [site + "post/1"],
            }
        )
    if weight is not None:
        payload["weight"] = weight
    response = client.post("/api/v1/admin/sources", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _default_fetchers() -> dict[str, StaticFetcher]:
    source_a_pages = {
        SITE_A: _index_html(
            [SITE_A + "dup", SITE_A + "ml", SITE_A + "view", SITE_A + "offtopic", SITE_A + "ad"]
        ),
        SITE_A + "dup": load_fixture("dup_a.html"),
        SITE_A + "ml": _article_html("原新闻", BASE),
        SITE_A + "view": _article_html("行业反应", REACTION),
        SITE_A + "offtopic": _article_html("随手记事", OFF_TOPIC),
        SITE_A + "ad": load_fixture("ad_page.html"),
    }
    source_b_pages = {
        SITE_B: _index_html([SITE_B + "dup-copy", SITE_B + "near-copy"]),
        SITE_B + "dup-copy": load_fixture("dup_b.html"),
        SITE_B + "near-copy": _article_html("转载", REPOST),
    }
    return {SITE_A: StaticFetcher(source_a_pages), SITE_B: StaticFetcher(source_b_pages)}


def _setup(
    client: TestClient, session: Session, headers: dict, *, fetchers=None
) -> SimpleNamespace:
    category_service.ensure_default_categories(session)
    source_a = _create_source(client, headers, "站点A", SITE_A, weight=5.0)
    source_b = _create_source(client, headers, "站点B", SITE_B, weight=1.0)
    spam = _create_source(client, headers, "垃圾站", SPAM, list_type="blacklist")

    fetchers = fetchers or _default_fetchers()
    reports = scheduler_service.run_due_sources(
        session,
        fetcher_factory=lambda source: fetchers[source.site_url],
        now_factory=lambda: FIXED_NOW,
    )

    return SimpleNamespace(
        source_a=source_a,
        source_b=source_b,
        spam=spam,
        fetchers=fetchers,
        reports=reports,
    )


def test_e2e_collection_dedup_and_browsing(
    client: TestClient, api_session: Session, admin_headers: dict[str, str]
) -> None:
    env = _setup(client, api_session, admin_headers)

    # 黑名单站点不会被抓取
    assert all(report.source_id != env.spam["id"] for report in env.reports)

    # 场景 1：正常采集展示（用户故事 1、4、5）
    listing = client.get("/api/v1/articles").json()
    # 可见文章：原新闻、行业反应、随手记事、完全相同文章（重复成员被隐藏）
    assert listing["total"] == 4
    titles = {item["title"] for item in listing["items"]}
    assert {"原新闻", "行业反应", "随手记事", "相同的文章标题"} <= titles

    sample = next(item for item in listing["items"] if item["title"] == "原新闻")
    assert sample["primary_category"]["name"] == "AI/机器学习"
    assert sample["primary_source"]["name"] == "站点A"
    assert sample["published_at"] is not None or sample["crawled_at"]

    # 场景 2：完全重复合并（用户故事 3、7）—— 两个来源合并为一条并全部可查
    groups = client.get("/api/v1/admin/dedup/groups", headers=admin_headers).json()
    group = next(
        item
        for item in groups["items"]
        if len(item["members"]) == 2 and item["members"][0]["title"] == "相同的文章标题"
    )
    assert len(group["members"]) == 2
    dup_detail = client.get(f"/api/v1/articles/{group['primary_id']}").json()
    assert len(dup_detail["sources"]) == 2
    assert {source["name"] for source in dup_detail["sources"]} == {"站点A", "站点B"}

    # 场景 3：近重复合并
    hits = client.get("/api/v1/admin/dedup/hits", headers=admin_headers).json()["items"]
    relation_types = {item["relation_type"] for item in hits}
    assert "exact_duplicate" in relation_types
    assert "near_duplicate" in relation_types

    # 场景 4：不同视角不合并，仅关联（用户故事 7）
    assert "related" in relation_types
    assert "行业反应" in titles  # 独立保留
    base_article = next(item for item in listing["items"] if item["title"] == "原新闻")
    base_detail = client.get(f"/api/v1/articles/{base_article['id']}").json()
    assert any(item["title"] == "行业反应" for item in base_detail["related_articles"])

    view_article = next(item for item in listing["items"] if item["title"] == "行业反应")
    view_detail = client.get(f"/api/v1/articles/{view_article['id']}").json()
    assert len(view_detail["sources"]) == 1  # 不同视角文章未被合并

    # 场景 5：未分类兜底（用户故事 2 的兜底）
    uncategorized = [item for item in listing["items"] if item["status"] == "uncategorized"]
    assert any(item["title"] == "随手记事" for item in uncategorized)
    assert any(item["primary_category"]["name"] == "其他" for item in uncategorized)

    # 低质量广告页不进入正式文章表
    assert all(item["title"] != "限时优惠活动" for item in listing["items"])

    # T19 新鲜度：来源维度最后更新时间
    sources = client.get("/api/v1/sources").json()["items"]
    source_a = next(item for item in sources if item["name"] == "站点A")
    assert source_a["last_success_at"] is not None

    # 用户故事 8/9 + T20：维护者效果概览与实际记录一致
    insights = client.get("/api/v1/admin/insights", headers=admin_headers).json()
    assert insights["dedup_stats"]["exact_duplicate"] == 1
    assert insights["dedup_stats"]["near_duplicate"] == 1
    assert insights["dedup_stats"]["related"] >= 1
    assert "其他" in insights["category_distribution"]


def test_e2e_reclassify_and_primary_switch(
    client: TestClient, api_session: Session, admin_headers: dict[str, str]
) -> None:
    _setup(client, api_session, admin_headers)

    # 场景 5（续）：维护者将未分类文章重新归类
    listing = client.get("/api/v1/articles").json()["items"]
    off_topic = next(item for item in listing if item["title"] == "随手记事")
    categories = client.get("/api/v1/admin/categories", headers=admin_headers).json()["items"]
    database = next(item for item in categories if item["name"] == "数据库")

    reclassify = client.post(
        f"/api/v1/admin/articles/{off_topic['id']}/category",
        json={"category_id": database["id"]},
        headers=admin_headers,
    )
    assert reclassify.status_code == 200
    assert reclassify.json()["status"] == "normal"
    filtered = client.get("/api/v1/articles", params={"category": "数据库"}).json()
    assert any(item["title"] == "随手记事" for item in filtered["items"])

    # 场景 6：主记录失效后切换（用户故事 7 的延伸）
    groups = client.get("/api/v1/admin/dedup/groups", headers=admin_headers).json()["items"]
    group = next(
        item
        for item in groups
        if len(item["members"]) == 2 and item["members"][0]["title"] == "相同的文章标题"
    )
    current_primary = group["primary_id"]
    other_member = next(
        member["id"] for member in group["members"] if member["id"] != current_primary
    )

    switched = client.post(
        f"/api/v1/admin/articles/{current_primary}/inaccessible", headers=admin_headers
    )
    assert switched.status_code == 200
    assert switched.json()["changed"] is True
    assert switched.json()["primary_id"] == other_member


def test_e2e_threshold_audit_and_continuous_update(
    client: TestClient, api_session: Session, admin_headers: dict[str, str]
) -> None:
    _setup(client, api_session, admin_headers)
    settings_url = "/api/v1/admin/dedup/settings"

    # 场景 7：阈值调整预览、变更记录与回滚
    assert client.get(settings_url, headers=admin_headers).json()["near_duplicate_threshold"] == 0.9

    preview = client.post(
        "/api/v1/admin/dedup/preview",
        json={"near_duplicate_threshold": 0.6},
        headers=admin_headers,
    )
    assert preview.status_code == 200
    assert preview.json()["proposed_threshold"] == 0.6
    assert "would_merge" in preview.json()

    assert (
        client.patch(
            settings_url, json={"near_duplicate_threshold": 0.6}, headers=admin_headers
        ).json()["near_duplicate_threshold"]
        == 0.6
    )
    history = client.get("/api/v1/admin/dedup/history", headers=admin_headers).json()
    assert len(history) == 1
    assert history[0]["old_value"] == "0.9"
    assert history[0]["new_value"] == "0.6"
    assert history[0]["actor"]

    rolled = client.post(
        "/api/v1/admin/dedup/rollback",
        json={"history_id": history[0]["id"]},
        headers=admin_headers,
    )
    assert rolled.json()["near_duplicate_threshold"] == 0.9

    # 用户故事 6：周期性更新带来新内容
    fetchers = _default_fetchers()
    fetchers[SITE_A].pages[SITE_A] = _index_html(
        [
            SITE_A + "dup",
            SITE_A + "ml",
            SITE_A + "view",
            SITE_A + "offtopic",
            SITE_A + "ad",
            SITE_A + "new",
        ]
    )
    fetchers[SITE_A].pages[SITE_A + "new"] = _article_html(
        "后续报道", "关于该人工智能模型的后续报道，包含新的训练数据与评测结果。"
    )

    later = FIXED_NOW + timedelta(days=2)
    reports = scheduler_service.run_due_sources(
        api_session,
        fetcher_factory=lambda source: fetchers[source.site_url],
        now_factory=lambda: later,
    )
    assert any(report.source_id for report in reports)

    titles = {item["title"] for item in client.get("/api/v1/articles").json()["items"]}
    assert "后续报道" in titles
