"""基于关键词/规则的主类别判定与标签抽取（T08）。

分类体系来自 T07 的受控类别（此处仅为各类别提供关键词规则，不写死类别清单本身）；
当一篇文章没有任何类别命中时返回 ``category_name=None``，由 T12 负责"未分类"兜底。
"""

from dataclasses import dataclass, field

# 类别关键词规则（可随类别体系演进调整；"其他"为兜底类别，不参与规则打分）
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "AI/机器学习": (
        "人工智能",
        "机器学习",
        "深度学习",
        "神经网络",
        "大模型",
        "训练",
        "推理",
        "算法",
        "AI",
    ),
    "Web 开发": (
        "前端",
        "后端",
        "React",
        "Vue",
        "JavaScript",
        "TypeScript",
        "HTML",
        "CSS",
        "接口",
        "API",
        "Web",
    ),
    "数据库": (
        "数据库",
        "SQL",
        "MySQL",
        "PostgreSQL",
        "Redis",
        "索引",
        "事务",
        "查询优化",
    ),
    "运维": (
        "运维",
        "部署",
        "Docker",
        "Kubernetes",
        "CI/CD",
        "监控",
        "容器",
        "服务器",
    ),
    "安全": (
        "安全",
        "漏洞",
        "加密",
        "攻击",
        "防护",
        "认证",
        "XSS",
        "注入",
    ),
    "产品设计": (
        "产品",
        "设计",
        "用户体验",
        "交互",
        "需求",
        "原型",
        "UX",
        "UI",
    ),
}

# 标签词汇表：命中即作为文章标签（一篇文章可有多个标签）
TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "机器学习": ("机器学习", "模型", "训练"),
    "深度学习": ("深度学习", "神经网络", "Transformer", "CNN"),
    "Python": ("python", "pip", "django", "flask"),
    "前端": ("前端", "react", "vue", "css"),
    "数据库": ("数据库", "sql", "索引"),
    "DevOps": ("docker", "kubernetes", "ci/cd", "部署"),
    "安全": ("安全", "漏洞", "加密"),
}

TITLE_WEIGHT = 3
BODY_WEIGHT = 1
MAX_TAGS = 5


@dataclass(frozen=True)
class Classification:
    """分类结果：至多一个主类别 + 若干标签。"""

    category_name: str | None
    tags: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)


def classify_text(
    title: str,
    content: str,
    *,
    allowed_categories: set[str] | None = None,
) -> Classification:
    """对标题/正文进行关键词打分，返回得分最高的类别与命中的标签。"""

    lowered_title = (title or "").lower()
    haystack = f"{title}\n{content}".lower()

    scores: dict[str, int] = {}
    for name, keywords in CATEGORY_KEYWORDS.items():
        if allowed_categories is not None and name not in allowed_categories:
            continue
        score = 0
        for keyword in keywords:
            needle = keyword.lower()
            if needle in lowered_title:
                score += TITLE_WEIGHT
            if needle in haystack:
                score += BODY_WEIGHT
        if score > 0:
            scores[name] = score

    category_name = max(scores, key=lambda name: scores[name]) if scores else None
    tags = [
        tag
        for tag, keywords in TAG_KEYWORDS.items()
        if any(keyword.lower() in haystack for keyword in keywords)
    ]
    return Classification(category_name=category_name, tags=tags[:MAX_TAGS], scores=scores)
