import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { confirmSubscription } from '../api/subscriptions'

/** 订阅确认页（T27）：从确认邮件跳转，凭 token 完成双确认。 */
export default function SubscriptionConfirmPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [state, setState] = useState<'loading' | 'done' | 'error'>('loading')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!token) {
      setState('error')
      setMessage('缺少确认凭证，请使用邮件中的完整链接')
      return
    }
    confirmSubscription(token)
      .then((result) => {
        setState('done')
        setMessage(
          result.status === 'confirmed'
            ? '订阅已确认，我们会按你选择的节奏发送摘要。'
            : '订阅状态已更新。',
        )
      })
      .catch((err: Error) => {
        setState('error')
        setMessage(err.message)
      })
  }, [token])

  return (
    <section className="space-y-4">
      <Link to="/" className="text-sm text-brand-600 hover:underline">
        ← 返回文章列表
      </Link>
      <h1 className="text-xl font-semibold text-slate-800">订阅确认</h1>
      {state === 'loading' && <p className="text-sm text-slate-600">正在确认…</p>}
      {state === 'done' && (
        <p className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {message}
        </p>
      )}
      {state === 'error' && (
        <div className="space-y-2">
          <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {message}
          </p>
          <Link to="/subscribe" className="text-sm text-brand-600 hover:underline">
            重新发起订阅
          </Link>
        </div>
      )}
    </section>
  )
}
