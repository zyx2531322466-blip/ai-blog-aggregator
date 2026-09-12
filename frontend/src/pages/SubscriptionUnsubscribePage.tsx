import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { fetchMySubscription, unsubscribe, type SubscriptionMe } from '../api/subscriptions'

/** 退订页（T27）：一键退订（可同时退订该邮箱的全部订阅），并展示当前订阅信息。 */
export default function SubscriptionUnsubscribePage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [state, setState] = useState<'loading' | 'ready' | 'done' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const [me, setMe] = useState<SubscriptionMe | null>(null)

  useEffect(() => {
    if (!token) {
      setState('error')
      setMessage('缺少退订凭证，请使用最新邮件中的退订链接')
      return
    }
    fetchMySubscription(token)
      .then((data) => {
        setMe(data)
        setState('ready')
      })
      .catch((err: Error) => {
        setState('error')
        setMessage(err.message)
      })
  }, [token])

  const handleUnsubscribe = async (scope: 'self' | 'all') => {
    try {
      const result = await unsubscribe(token, scope)
      setState('done')
      setMessage(
        scope === 'all'
          ? `已退订该邮箱的全部订阅（共 ${result.affected} 条）`
          : '已退订该订阅，不会再收到推送',
      )
    } catch (err) {
      setState('error')
      setMessage((err as Error).message)
    }
  }

  return (
    <section className="space-y-4">
      <Link to="/" className="text-sm text-brand-600 hover:underline">
        ← 返回文章列表
      </Link>
      <h1 className="text-xl font-semibold text-slate-800">退订</h1>

      {state === 'loading' && <p className="text-sm text-slate-600">正在加载订阅信息…</p>}

      {state === 'ready' && me && (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">
            订阅邮箱：{me.email} · 节奏：{me.frequency === 'daily' ? '每天' : '每周'} · 方向：
            {me.topics.map((topic) => topic.value).join('、') || '无'}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => handleUnsubscribe('self')}
              className="rounded bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
            >
              退订该订阅
            </button>
            <button
              type="button"
              onClick={() => handleUnsubscribe('all')}
              className="rounded border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:border-brand-400"
            >
              退订该邮箱的全部订阅
            </button>
          </div>
        </div>
      )}

      {state === 'done' && (
        <p className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {message}
        </p>
      )}

      {state === 'error' && (
        <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {message}
        </p>
      )}
    </section>
  )
}
