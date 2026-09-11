"""热门技术博客种子来源（一键让站点有可浏览的内容）。

来源清单来自公开推荐（中文独立博客列表、开发者 RSS 推荐等）的人工筛选，并逐条核对：

- ``/robots.txt`` 允许本爬虫抓取（已排除返回 403 的科学空间、TLS 握手异常的德哥 PostgreSQL）；
- 站点首页的链接能被 T05 的文章发现逻辑识别为**文章详情页**（排除首页只能发现栏目页的站点）。

用法：

```bash
python -m app.scripts.seed_sources            # 幂等写入缺失的来源（已存在的跳过）
python -m app.scripts.seed_sources --dry-run  # 只打印将要写入的来源
```

在容器内执行：

```bash
docker compose -f infra/docker-compose.yml exec api python -m app.scripts.seed_sources
```
"""

import argparse
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import SourceListType, UpdateFrequency
from app.db.models import Source

DEFAULT_EXCLUDE_KEYWORDS = ("招聘", "广告", "优惠", "赞助")


@dataclass(frozen=True)
class SeedSource:
    """一条种子来源定义。"""

    name: str
    site_url: str
    focus_area_name: str
    focus_area_description: str
    keywords: tuple[str, ...]
    example_urls: tuple[str, ...]
    weight: float
    update_frequency: UpdateFrequency = UpdateFrequency.NORMAL
    exclude_keywords: tuple[str, ...] = DEFAULT_EXCLUDE_KEYWORDS


SEED_SOURCES: tuple[SeedSource, ...] = (
    SeedSource(
        name="阮一峰的网络日志",
        site_url="https://www.ruanyifeng.com/blog/",
        focus_area_name="Web 开发与科技趋势",
        focus_area_description="前端、JavaScript、工程实践与每周科技爱好者周刊",
        keywords=("前端", "JavaScript", "工程实践", "科技趋势"),
        example_urls=("https://www.ruanyifeng.com/blog/2026/09/weekly-issue-412.html",),
        weight=5.0,
        update_frequency=UpdateFrequency.HIGH,
    ),
    SeedSource(
        name="云风的 BLOG",
        site_url="https://blog.codingnow.com/",
        focus_area_name="系统设计与游戏开发",
        focus_area_description="C/Lua、引擎实现、系统设计与工程文化",
        keywords=("系统设计", "架构", "C", "Lua"),
        example_urls=("https://blog.codingnow.com/2026/07/learning_english.html",),
        weight=5.0,
        update_frequency=UpdateFrequency.LOW,
    ),
    SeedSource(
        name="Draveness",
        site_url="https://draveness.me/",
        focus_area_name="后端与分布式系统",
        focus_area_description="Go、编译原理、分布式与系统设计深度长文",
        keywords=("Go", "分布式", "系统设计", "编译原理"),
        example_urls=("https://draveness.me/2020-summary/",),
        weight=4.5,
        update_frequency=UpdateFrequency.LOW,
    ),
    SeedSource(
        name="离别歌",
        site_url="https://www.leavesongs.com/",
        focus_area_name="Web 安全",
        focus_area_description="代码审计、漏洞分析与安全攻防实践",
        keywords=("安全", "漏洞", "代码审计", "渗透测试"),
        example_urls=("https://www.leavesongs.com/PENETRATION/try-code-security.html",),
        weight=5.0,
        update_frequency=UpdateFrequency.NORMAL,
    ),
    SeedSource(
        name="张鑫旭的博客",
        site_url="https://www.zhangxinxu.com/wordpress/",
        focus_area_name="前端与 CSS",
        focus_area_description="CSS、JavaScript 与浏览器实现的细节与实战",
        keywords=("前端", "CSS", "JavaScript", "浏览器"),
        example_urls=("https://www.zhangxinxu.com/php/microCode",),
        weight=4.0,
        update_frequency=UpdateFrequency.NORMAL,
    ),
    SeedSource(
        name="小林coding",
        site_url="https://xiaolincoding.com/",
        focus_area_name="计算机基础与后端",
        focus_area_description="图解网络、操作系统、MySQL、Redis 等基础知识体系",
        keywords=("网络", "操作系统", "MySQL", "Redis"),
        example_urls=("https://xiaolincoding.com/project/mewhelp.html",),
        weight=3.5,
        update_frequency=UpdateFrequency.LOW,
    ),
    SeedSource(
        name="onevcat",
        site_url="https://onevcat.com/",
        focus_area_name="客户端与工程实践",
        focus_area_description="iOS、Swift、AI 辅助开发与工程实践思考",
        keywords=("iOS", "Swift", "工程实践", "独立开发"),
        example_urls=("https://onevcat.com/2026/07/coding-not-funny-anymore/",),
        weight=4.0,
        update_frequency=UpdateFrequency.NORMAL,
    ),
    SeedSource(
        name="Simon Willison",
        site_url="https://simonwillison.net/",
        focus_area_name="AI 与 Python",
        focus_area_description="大模型应用、Python 生态与开源工具实践",
        keywords=("AI", "大模型", "Python", "开源"),
        example_urls=("https://simonwillison.net/2026/Sep/11/soft-deprecating-re-match/",),
        weight=5.0,
        update_frequency=UpdateFrequency.HIGH,
    ),
    SeedSource(
        name="Julia Evans",
        site_url="https://jvns.ca/",
        focus_area_name="系统与调试",
        focus_area_description="Linux、网络、数据库与调试技巧的通俗讲解",
        keywords=("Linux", "调试", "网络", "SQL"),
        example_urls=("https://jvns.ca/blog/2026/07/21/more-nice-django-things/",),
        weight=4.5,
        update_frequency=UpdateFrequency.HIGH,
    ),
    SeedSource(
        name="Dan Luu",
        site_url="https://danluu.com/",
        focus_area_name="工程与性能",
        focus_area_description="硬件性能、工程文化与技术决策的数据驱动分析",
        keywords=("性能", "硬件", "工程文化", "分布式"),
        example_urls=("https://danluu.com/agentic-testing/",),
        weight=4.0,
        update_frequency=UpdateFrequency.LOW,
    ),
    SeedSource(
        name="Go Blog",
        site_url="https://go.dev/blog/",
        focus_area_name="Go 语言官方博客",
        focus_area_description="Go 语言特性、工具链与运行时的一手发布说明",
        keywords=("Go", "语言特性", "运行时", "工具链"),
        example_urls=("https://go.dev/blog/goroutine-leak-profiles",),
        weight=4.5,
        update_frequency=UpdateFrequency.HIGH,
    ),
    SeedSource(
        name="Rust Blog",
        site_url="https://blog.rust-lang.org/",
        focus_area_name="Rust 语言官方博客",
        focus_area_description="Rust 版本发布、语言演进与社区调查",
        keywords=("Rust", "语言特性", "发布说明", "社区"),
        example_urls=("https://blog.rust-lang.org/2026/09/07/rust-debugging-survey-2026-results/",),
        weight=4.5,
        update_frequency=UpdateFrequency.HIGH,
    ),
)


@dataclass
class SeedReport:
    """种子写入结果。"""

    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.created) + len(self.skipped)


def seed_sources(session: Session, *, dry_run: bool = False) -> SeedReport:
    """按 ``site_url`` 幂等写入种子来源（已存在则跳过）。"""

    report = SeedReport()
    existing = {url for (url,) in session.execute(select(Source.site_url)).all()}

    for entry in SEED_SOURCES:
        if entry.site_url in existing:
            report.skipped.append(entry.name)
            continue
        report.created.append(entry.name)
        existing.add(entry.site_url)
        if dry_run:
            continue
        session.add(
            Source(
                name=entry.name,
                site_url=entry.site_url,
                description=entry.focus_area_description,
                focus_area_name=entry.focus_area_name,
                focus_area_description=entry.focus_area_description,
                keywords=list(entry.keywords),
                exclude_keywords=list(entry.exclude_keywords),
                example_urls=list(entry.example_urls),
                counter_example_urls=[],
                list_type=SourceListType.WHITELIST,
                weight=entry.weight,
                update_frequency=entry.update_frequency,
            )
        )

    if not dry_run:
        session.commit()
    return report


def main(argv: list[str] | None = None) -> int:
    """命令行入口：``python -m app.scripts.seed_sources [--dry-run]``。"""

    parser = argparse.ArgumentParser(description="写入热门技术博客种子来源（幂等）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要写入的来源")
    args = parser.parse_args(argv)

    from app.db.session import get_session_factory

    session = get_session_factory()()
    try:
        report = seed_sources(session, dry_run=args.dry_run)
    finally:
        session.close()

    mode = "（dry-run，未写库）" if args.dry_run else ""
    print(f"种子来源共 {report.total} 条{mode}")
    print(f"  新增 {len(report.created)} 条: {', '.join(report.created) or '-'}")
    print(f"  跳过 {len(report.skipped)} 条（已存在）: {', '.join(report.skipped) or '-'}")
    return 0


if __name__ == "__main__":  # pragma: no cover - 命令行入口
    raise SystemExit(main())
