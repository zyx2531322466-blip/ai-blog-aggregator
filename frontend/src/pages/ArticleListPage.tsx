import { useEffect, useState } from 'react'

import { fetchArticles } from '../api/articles'
import type { PublicCategory } from '../api/categories'
import { fetchCategories } from '../api/categories'
import type { PublicSource } from '../api/sources'
import { fetchSources } from '../api/sources'
import type { ArticleListResponse } from '../api/types'
import ArticleCard from '../components/ArticleCard'
import CategoryFilter from '../components/CategoryFilter'
import Pagination from '../components/Pagination'
import SourceFreshness from '../components/SourceFreshness'

export const PAGE_SIZE = 10

/** 文章列表页：支持分类筛选与分页，并展示来源更新状态（T19）。 */
export default function ArticleListPage() {
  const [categories, setCategories] = useState<PublicCategory[]>([])
  const [sources, setSources] = useState<PublicSource[]>([])
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<ArticleListResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchCategories(controller.signal)
      .then(setCategories)
      .catch(() => setCategories([]))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    fetchSources(controller.signal)
      .then(setSources)
      .catch(() => setSources([]))
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setError(null)
    fetchArticles(
      { category: selectedCategory ?? undefined, page, page_size: PAGE_SIZE },
      controller.signal,
    )
      .then(setData)
      .catch((err: Error) => {
        if (err.name !== 'AbortError') {
          setError('文章加载失败，请稍后重试')
        }
      })
    return () => controller.abort()
  }, [selectedCategory, page])

  const handleSelectCategory = (category: string | null) => {
    setSelectedCategory(category)
    setPage(1)
  }

  return (
    <section className="space-y-5">
      <h1 className="text-xl font-semibold text-slate-800">文章列表</h1>
      <CategoryFilter
        categories={categories}
        selected={selectedCategory}
        onSelect={handleSelectCategory}
      />

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      <div className="space-y-4">
        {data?.items.map((article) => (
          <ArticleCard key={article.id} article={article} />
        ))}
      </div>

      {data && data.total === 0 ? <p className="text-sm text-slate-500">该分类下暂无文章</p> : null}

      {data ? (
        <Pagination
          page={data.page}
          pageSize={data.page_size}
          total={data.total}
          onChange={setPage}
        />
      ) : null}

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-700">来源更新状态</h2>
        <SourceFreshness sources={sources} />
      </section>
    </section>
  )
}
