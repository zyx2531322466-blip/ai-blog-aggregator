import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  createWikiEntry,
  fetchKnowledgeDecisions,
  fetchKnowledgeStats,
  fetchWikiEntries,
  overrideArticleKnowledge,
  retireWikiEntry,
  type KnowledgeDecisionList,
  type KnowledgeStats,
  type WikiEntry,
  type WikiEntryList,
} from '../api/notifications'
import { formatDate } from '../utils/format'

const DECISION_LABELS: Record<string, string> = {
  new_knowledge: '全新知识',
  partial: '部分新增',
  covered: '知识已覆盖',
  pending: '待判定',
}

const ENTRY_STATUS_LABELS: Record<string, string> = {
  active: '生效中',
  retired: '已废止',
  merged: '已合并',
}

/** 维护者：知识 Wiki 管理与判定复核（T25–T27）。 */
export default function AdminWikiPage() {
  const [token, setToken] = useState('')
  const [entries, setEntries] = useState<WikiEntryList | null>(null)
  const [decisions, setDecisions] = useState<KnowledgeDecisionList | null>(null)
  const [stats, setStats] = useState<KnowledgeStats | null>(null)
  const [name, setName] = useState('')
  const [summary, setSummary] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const load = useCallback(async (adminToken: string) => {
    setError(null)
    try {
      const [entryList, decisionList, knowledgeStats] = await Promise.all([
        fetchWikiEntries(adminToken),
        fetchKnowledgeDecisions(adminToken),
        fetchKnowledgeStats(adminToken),
      ])
      setEntries(entryList)
      setDecisions(decisionList)
      setStats(knowledgeStats)
    } catch (err) {
      const reason = (err as Error).message
      setError(reason === 'UNAUTHORIZED' ? '鉴权失败，请检查管理令牌' : reason)
    }
  }, [])

  useEffect(() => {
    if (token) {
      void load(token)
    }
  }, [load, token])

  const handleCreate = async (event: React.FormEvent) => {
    event.preventDefault()
    setMessage(null)
    if (!name.trim()) {
      setError('请填写知识点名称')
      return
    }
    try {
      await createWikiEntry(token, { name: name.trim(), summary })
      setName('')
      setSummary('')
      setMessage('知识点条目已创建')
      await load(token)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const handleRetire = async (entry: WikiEntry) => {
    try {
      await retireWikiEntry(token, entry.id)
      setMessage(`已废止「${entry.name}」，后续判定不再把它当作已覆盖依据`)
      await load(token)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const handleOverride = async (articleId: string) => {
    try {
      await overrideArticleKnowledge(token, articleId, {
        decision: 'new_knowledge',
        reason: '维护者复核：该文包含新增信息',
      })
      setMessage('已改判为"全新知识"，该文将重新出现在列表中')
      await load(token)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <section className="space-y-6">
      <Link to="/admin" className="text-sm text-brand-600 hover:underline">
        ← 返回维护者概览
      </Link>
      <h1 className="text-xl font-semibold text-slate-800">知识 Wiki 与判定复核</h1>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-sm text-slate-700">
          管理令牌
          <input
            type="password"
            aria-label="管理令牌"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            className="ml-2 rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
        <button
          type="button"
          onClick={() => load(token)}
          className="rounded bg-brand-600 px-3 py-1.5 text-sm text-white hover:bg-brand-700"
        >
          加载
        </button>
      </div>

      {error && (
        <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>
      )}
      {message && (
        <p className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {message}
        </p>
      )}

      {stats && (
        <div className="rounded border border-slate-200 p-3 text-sm text-slate-600">
          因知识重复被筛：{stats.filtered_total} 篇 · 部分新增：{stats.partial_total} 篇 · 待判定：
          {stats.pending_total} 篇 · 今日模型调用：{stats.llm_usage.calls_today} 次（失败{' '}
          {stats.llm_usage.failures_today} 次，tokens {stats.llm_usage.tokens_today}）
        </div>
      )}

      <form className="space-y-2 rounded border border-slate-200 p-3" onSubmit={handleCreate}>
        <h2 className="text-sm font-semibold text-slate-700">新增知识点</h2>
        <div className="flex flex-wrap gap-2">
          <input
            aria-label="知识点名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：Raft 选主流程"
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <input
            aria-label="知识点摘要"
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            placeholder="一句话摘要"
            className="w-64 rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <button
            type="submit"
            className="rounded bg-brand-600 px-3 py-1.5 text-sm text-white hover:bg-brand-700"
          >
            新增
          </button>
        </div>
      </form>

      {entries && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-700">知识点条目（共 {entries.total}）</h2>
          <ul className="space-y-1 text-sm">
            {entries.items.map((entry) => (
              <li
                key={entry.id}
                className="flex flex-wrap items-center gap-2 border-t border-slate-100 py-1"
              >
                <span className="font-medium text-slate-700">{entry.name}</span>
                <span className="text-xs text-slate-500">
                  {ENTRY_STATUS_LABELS[entry.status] ?? entry.status} ·
                  {entry.created_by === 'human' ? '人工录入' : '系统提炼'}
                </span>
                {entry.status === 'active' && (
                  <button
                    type="button"
                    onClick={() => handleRetire(entry)}
                    className="text-xs text-red-600 hover:underline"
                  >
                    废止
                  </button>
                )}
              </li>
            ))}
            {entries.items.length === 0 && <li className="py-2 text-slate-400">暂无条目</li>}
          </ul>
        </div>
      )}

      {decisions && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-700">判定记录（共 {decisions.total}）</h2>
          <ul className="space-y-1 text-sm">
            {decisions.items.map((decision) => (
              <li key={decision.id} className="space-y-1 border-t border-slate-100 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {DECISION_LABELS[decision.decision] ?? decision.decision}
                  </span>
                  <span className="text-xs text-slate-500">
                    {decision.similarity !== null
                      ? `相似度 ${decision.similarity.toFixed(2)} · `
                      : ''}
                    {decision.model ?? '—'} · {decision.actor === 'human' ? '人工' : '系统'} ·
                    {formatDate(decision.created_at)}
                  </span>
                  {decision.decision === 'covered' && (
                    <button
                      type="button"
                      onClick={() => handleOverride(decision.article_id)}
                      className="text-xs text-brand-600 hover:underline"
                    >
                      改判为全新知识
                    </button>
                  )}
                </div>
                {decision.rationale && (
                  <p className="text-xs text-slate-500">依据：{decision.rationale}</p>
                )}
              </li>
            ))}
            {decisions.items.length === 0 && <li className="py-2 text-slate-400">暂无判定记录</li>}
          </ul>
        </div>
      )}

      <p className="rounded border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
        判定原则：只有证据充分时才判定"知识已覆盖"；任何不确定情形都会判为新增知识，
        且维护者可随时改判。文章内容会发送给外部 LLM 服务用于知识点提炼，订阅者邮箱不会参与该过程。
      </p>
    </section>
  )
}
