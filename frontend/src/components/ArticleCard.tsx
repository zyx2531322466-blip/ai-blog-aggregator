import { Link } from 'react-router-dom'

import type { ArticleListItem } from '../api/types'
import { formatDate } from '../utils/format'

interface ArticleCardProps {
  article: ArticleListItem
}

/** 列表项卡片：统一展示标题/摘要/类别/标签/来源/时间。 */
export default function ArticleCard({ article }: ArticleCardProps) {
  const categoryName = article.primary_category?.name

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-lg font-semibold text-brand-700">
        <Link to={`/articles/${article.id}`} className="hover:underline">
          {article.title}
        </Link>
      </h2>
      {article.summary ? <p className="mt-2 text-sm text-slate-600">{article.summary}</p> : null}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
        {categoryName ? (
          <span className="rounded bg-brand-50 px-2 py-0.5 text-brand-700">{categoryName}</span>
        ) : null}
        {article.tags.map((tag) => (
          <span key={tag} className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">
            {tag}
          </span>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        {article.primary_source ? <span>{article.primary_source.name}</span> : null}
        {article.published_at ? (
          <time dateTime={article.published_at}>发布于 {formatDate(article.published_at)}</time>
        ) : null}
        <time dateTime={article.crawled_at}>采集于 {formatDate(article.crawled_at)}</time>
        {article.merged_sources_count > 0 ? (
          <span data-testid="merged-count">共 {article.sources_count} 个来源</span>
        ) : null}
      </div>
    </article>
  )
}
