import { useState } from 'react'
import { Link } from 'react-router-dom'

import { fetchInsights } from '../api/insights'
import type { Insights } from '../api/insights'

const DEDUP_LABELS: Record<string, string> = {
  exact_duplicate: '完全重复',
  near_duplicate: '近重复',
  related: '关联推荐',
  merged_duplicates: '合并去重合计',
  total_articles: '文章总数',
  unique_articles: '去重后独立文章',
}

const ADMIN_ENTRIES = [
  { to: '/admin/sources', label: '来源配置' },
  { to: '/admin/categories', label: '类别管理' },
  { to: '/admin/dedup', label: '去重策略管理' },
  { to: '/admin/notifications', label: '订阅与推送管理' },
  { to: '/admin/wiki', label: '知识 Wiki 与判定复核' },
]

/** 维护者效果概览页（T20）：展示统计并提供各管理入口。 */
export default function AdminInsightsPage() {
  const [token, setToken] = useState('')
  const [insights, setInsights] = useState<Insights | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleLoad = async () => {
    setError(null)
    try {
      setInsights(await fetchInsights(token))
    } catch (err) {
      setInsights(null)
      setError((err as Error).message === 'UNAUTHORIZED' ? '鉴权失败，请检查管理令牌' : '加载失败')
    }
  }

  return (
    <section className="space-y-5">
      <Link to="/" className="text-sm text-brand-600 hover:underline">
        ← 返回文章列表
      </Link>
      <h1 className="text-xl font-semibold text-slate-800">维护者效果概览</h1>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-sm text-slate-600" htmlFor="admin-token">
          管理令牌
        </label>
        <input
          id="admin-token"
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <button
          type="button"
          onClick={handleLoad}
          className="rounded bg-brand-600 px-3 py-1 text-sm text-white"
        >
          加载概览
        </button>
      </div>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      {insights ? (
        <div className="grid gap-4 md:grid-cols-2">
          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-700">分类分布</h2>
            <ul className="space-y-1 text-sm text-slate-600">
              {Object.entries(insights.category_distribution).map(([name, count]) => (
                <li key={name} className="flex justify-between">
                  <span>{name}</span>
                  <span data-testid={`category-${name}`}>{count}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-semibold text-slate-700">去重命中统计</h2>
            <ul className="space-y-1 text-sm text-slate-600">
              {Object.entries(insights.dedup_stats).map(([key, count]) => (
                <li key={key} className="flex justify-between">
                  <span>{DEDUP_LABELS[key] ?? key}</span>
                  <span data-testid={`dedup-${key}`}>{count}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      ) : null}

      <nav aria-label="管理入口" className="flex flex-wrap gap-3 text-sm">
        {ADMIN_ENTRIES.map((entry) => (
          <Link key={entry.to} to={entry.to} className="text-brand-600 hover:underline">
            {entry.label}
          </Link>
        ))}
      </nav>
    </section>
  )
}
