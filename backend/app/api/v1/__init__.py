"""v1 版本 API 路由聚合。"""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    admin_articles,
    admin_categories,
    admin_dedup,
    admin_insights,
    admin_knowledge,
    admin_notifications,
    admin_sources,
    admin_wiki,
    articles,
    categories,
    sources,
    subscriptions,
)

api_router = APIRouter()
api_router.include_router(articles.router)
api_router.include_router(categories.router)
api_router.include_router(sources.router)
api_router.include_router(subscriptions.router)
api_router.include_router(admin.router)
api_router.include_router(admin_sources.router)
api_router.include_router(admin_categories.router)
api_router.include_router(admin_articles.router)
api_router.include_router(admin_dedup.router)
api_router.include_router(admin_insights.router)
api_router.include_router(admin_notifications.router)
api_router.include_router(admin_wiki.router)
api_router.include_router(admin_knowledge.router)
