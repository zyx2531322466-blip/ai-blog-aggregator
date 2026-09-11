import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { fetchArticle } from '../api/articles'
import type { ArticleDetail } from '../api/types'
import SourceList from '../components/SourceList'
import { formatDate } from '../utils/format'

/** 文章详情页：展示正文与合并组的全部来源。 */
export default function ArticleDetailPage() {
  const { articleId } = useParams<{ articleId: string }>()
  const [article, setArticle] = useState<ArticleDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!articleId) {
      return
    }
    const controller = new AbortController()
    setError(null)
    fetchArticle(articleId, controller.signal)
      .then(setArticle)
      .catch((err: Error) => {
        if (err.name !== 'AbortError') {
          setError('文章加载失败，请稍后重试')
        }
      })
    return () => controller.abort()
  }, [articleId])

  if (error) {
    return <p className="text-sm text-red-600">{error}</p>
  }
  if (!article) {
    return null
  }

  const categoryName = article.primary_category?.name

  return (
    <article className="space-y-4">
      <Link to="/" className="text-sm text-brand-600 hover:underline">
        ← 返回列表
      </Link>

      <header className="space-y-2">
        <h1 className="text-2xl font-semibold text-slate-800">{article.title}</h1>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {categoryName ? (
            <span className="rounded bg-brand-50 px-2 py-0.5 text-brand-700">{categoryName}</span>
          ) : null}
          {article.tags.map((tag) => (
            <span key={tag} className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">
              {tag}
            </span>
          ))}
        </div>
        <p className="text-xs text-slate-500">
          原文发布时间：{formatDate(article.published_at)} · 采集时间：
          {formatDate(article.crawled_at)}
        </p>
      </header>

      <div className="whitespace-pre-line rounded-lg border border-slate-200 bg-white p-4 text-sm leading-6 text-slate-700">
        {article.content}
      </div>

      <section className="space-y-2">
        <h2 className="text-base font-semibold text-slate-700">来源（{article.sources.length}）</h2>
        <SourceList sources={article.sources} />
      </section>
    </article>
  )
}
