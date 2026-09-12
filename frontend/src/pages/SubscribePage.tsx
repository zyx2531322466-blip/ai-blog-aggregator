import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  createSubscription,
  fetchTopicOptions,
  type SubscriptionCreated,
  type SubscriptionTopicInput,
  type TopicOptions,
} from '../api/subscriptions'

const FREQUENCY_LABELS: Record<string, string> = {
  daily: '每天',
  weekly: '每周',
}

const TYPE_LABELS: Record<string, string> = {
  category: '类别',
  tag: '标签',
  source: '来源',
}

/** 订阅页（T27）：选择感兴趣的方向与节奏，提交邮箱后进入双确认流程。 */
export default function SubscribePage() {
  const [options, setOptions] = useState<TopicOptions | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selected, setSelected] = useState<SubscriptionTopicInput[]>([])
  const [keyword, setKeyword] = useState('')
  const [email, setEmail] = useState('')
  const [frequency, setFrequency] = useState('weekly')
  const [maxItems, setMaxItems] = useState(10)
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [created, setCreated] = useState<SubscriptionCreated | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchTopicOptions(controller.signal)
      .then((data) => {
        setOptions(data)
        if (data.frequencies.length > 0) {
          setFrequency(data.frequencies.includes('weekly') ? 'weekly' : data.frequencies[0])
        }
      })
      .catch(() => setLoadError('订阅方向加载失败，请稍后重试'))
    return () => controller.abort()
  }, [])

  const selectedKeys = useMemo(
    () => new Set(selected.map((topic) => `${topic.type}:${topic.value}`)),
    [selected],
  )

  const toggle = (type: SubscriptionTopicInput['type'], value: string) => {
    const key = `${type}:${value}`
    setSelected((current) =>
      current.some((topic) => `${topic.type}:${topic.value}` === key)
        ? current.filter((topic) => `${topic.type}:${topic.value}` !== key)
        : [...current, { type, value }],
    )
  }

  const addKeyword = () => {
    const value = keyword.trim()
    if (!value || selectedKeys.has(`keyword:${value}`)) {
      return
    }
    setSelected((current) => [...current, { type: 'keyword', value }])
    setKeyword('')
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setFormError(null)
    if (!email.includes('@')) {
      setFormError('请填写正确的邮箱地址')
      return
    }
    if (selected.length === 0) {
      setFormError('请至少选择一个订阅方向')
      return
    }
    setSubmitting(true)
    try {
      const result = await createSubscription({
        email,
        topics: selected,
        frequency,
        max_items: maxItems,
      })
      setCreated(result)
    } catch (err) {
      setFormError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  if (created) {
    return (
      <section className="space-y-4" aria-label="订阅已提交">
        <h1 className="text-xl font-semibold text-slate-800">请查收确认邮件</h1>
        <p className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
          {created.message}
        </p>
        <p className="text-sm text-slate-600">
          确认链接有效期至 {new Date(created.confirm_expires_at).toLocaleString('zh-CN')}。
          只有点击邮件中的确认链接后，订阅才会生效。
        </p>
        <Link to="/" className="text-sm text-brand-600 hover:underline">
          ← 返回文章列表
        </Link>
      </section>
    )
  }

  return (
    <section className="space-y-5">
      <Link to="/" className="text-sm text-brand-600 hover:underline">
        ← 返回文章列表
      </Link>
      <h1 className="text-xl font-semibold text-slate-800">订阅感兴趣的方向</h1>
      <p className="text-sm text-slate-600">
        选择你关心的类别、标签、来源或关键词，我们会按你选择的节奏把新内容摘要发到你的邮箱。
      </p>

      {loadError && (
        <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {loadError}
        </p>
      )}

      <form className="space-y-5" onSubmit={handleSubmit}>
        {options &&
          (['categories', 'tags', 'sources'] as const).map((group) => (
            <fieldset key={group} className="space-y-2">
              <legend className="text-sm font-medium text-slate-700">
                {group === 'categories' ? '按类别' : group === 'tags' ? '按标签' : '按来源'}
              </legend>
              <div className="flex flex-wrap gap-2">
                {options[group].length === 0 && (
                  <span className="text-xs text-slate-400">暂无可选项</span>
                )}
                {options[group].map((option) => {
                  const type =
                    group === 'categories' ? 'category' : group === 'tags' ? 'tag' : 'source'
                  const key = `${type}:${option.value}`
                  const active = selectedKeys.has(key)
                  return (
                    <button
                      key={key}
                      type="button"
                      aria-pressed={active}
                      onClick={() => toggle(type as SubscriptionTopicInput['type'], option.value)}
                      className={`rounded-full border px-3 py-1 text-sm ${
                        active
                          ? 'border-brand-500 bg-brand-50 text-brand-700'
                          : 'border-slate-300 bg-white text-slate-600 hover:border-brand-400'
                      }`}
                    >
                      {TYPE_LABELS[type] ?? type}：{option.name ?? option.value}
                    </button>
                  )
                })}
              </div>
            </fieldset>
          ))}

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-slate-700">按关键词</legend>
          <div className="flex gap-2">
            <input
              aria-label="关键词"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="例如：向量数据库"
              className="w-48 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <button
              type="button"
              onClick={addKeyword}
              className="rounded border border-slate-300 px-3 py-1 text-sm text-slate-700 hover:border-brand-400"
            >
              添加关键词
            </button>
          </div>
        </fieldset>

        <div className="space-y-2">
          <p className="text-sm text-slate-700">已选择（{selected.length}）：</p>
          <ul className="flex flex-wrap gap-2 text-xs text-slate-600">
            {selected.map((topic) => (
              <li key={`${topic.type}:${topic.value}`} className="rounded bg-slate-100 px-2 py-1">
                {TYPE_LABELS[topic.type] ?? '关键词'}：{topic.value}
              </li>
            ))}
            {selected.length === 0 && <li className="text-slate-400">尚未选择任何方向</li>}
          </ul>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-slate-700">
            邮箱
            <input
              type="email"
              aria-label="邮箱"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="text-sm text-slate-700">
            推送节奏
            <select
              aria-label="推送节奏"
              value={frequency}
              onChange={(event) => setFrequency(event.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            >
              {(options?.frequencies ?? ['daily', 'weekly']).map((item) => (
                <option key={item} value={item}>
                  {FREQUENCY_LABELS[item] ?? item}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm text-slate-700">
            单封邮件最多条数
            <input
              type="number"
              aria-label="单封邮件最多条数"
              min={1}
              max={50}
              value={maxItems}
              onChange={(event) => setMaxItems(Number(event.target.value))}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
        </div>

        {formError && (
          <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {formError}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {submitting ? '提交中…' : '提交订阅'}
        </button>
      </form>

      <p className="rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
        说明：订阅是匿名的，我们只保存你的邮箱与订阅偏好，可随时一键退订或删除订阅数据。
        另外，本站的文章内容会发送给外部 LLM 服务用于提炼"知识点"，以便筛掉你已经看过的重复知识；
        <strong>你的邮箱不会参与该过程</strong>。
      </p>
    </section>
  )
}
