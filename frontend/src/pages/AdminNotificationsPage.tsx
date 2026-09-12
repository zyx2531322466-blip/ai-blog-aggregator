import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  fetchAdminSubscriptions,
  fetchDeliveryHealth,
  fetchDigestDetail,
  fetchDigests,
  fetchNotificationSettings,
  runDigests,
  updateNotificationSettings,
  type AdminSubscriptionList,
  type DeliveryHealth,
  type DigestDetail,
  type DigestList,
  type NotificationSettings,
} from '../api/notifications'
import { formatDate } from '../utils/format'

const STATUS_LABELS: Record<string, string> = {
  pending: '待投递',
  sent: '已发送',
  failed: '发送失败',
  skipped_empty: '空周期跳过',
  confirmed: '已确认',
  pending_confirmation: '待确认',
  unsubscribed: '已退订',
}

/** 维护者：推送记录与设置（T24/T27）。 */
export default function AdminNotificationsPage() {
  const [token, setToken] = useState('')
  const [subscriptions, setSubscriptions] = useState<AdminSubscriptionList | null>(null)
  const [digests, setDigests] = useState<DigestList | null>(null)
  const [detail, setDetail] = useState<DigestDetail | null>(null)
  const [settings, setSettings] = useState<NotificationSettings | null>(null)
  const [health, setHealth] = useState<DeliveryHealth | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (adminToken: string) => {
    setError(null)
    try {
      const [subscriptionList, digestList, current, deliveryHealth] = await Promise.all([
        fetchAdminSubscriptions(adminToken),
        fetchDigests(adminToken),
        fetchNotificationSettings(adminToken),
        fetchDeliveryHealth(adminToken),
      ])
      setSubscriptions(subscriptionList)
      setDigests(digestList)
      setSettings(current)
      setHealth(deliveryHealth)
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

  const handleRun = async (dryRun: boolean) => {
    setMessage(null)
    try {
      const result = await runDigests(token, { dry_run: dryRun })
      if (result.dry_run) {
        const planned = result.planned.reduce((sum, item) => sum + item.planned_items, 0)
        setMessage(`预演完成：本次将推送 ${planned} 篇（未真实发送）`)
      } else {
        setMessage(
          `已执行推送：发送 ${result.sent} 封、失败 ${result.failed} 封、空周期跳过 ${result.skipped_empty} 条`,
        )
      }
      await load(token)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const handleTogglePause = async () => {
    if (!settings) {
      return
    }
    try {
      setSettings(await updateNotificationSettings(token, { sends_paused: !settings.sends_paused }))
      await load(token)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const handleOpenDetail = async (digestId: string) => {
    try {
      setDetail(await fetchDigestDetail(token, digestId))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <section className="space-y-6">
      <Link to="/admin" className="text-sm text-brand-600 hover:underline">
        ← 返回维护者概览
      </Link>
      <h1 className="text-xl font-semibold text-slate-800">订阅与推送管理</h1>

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
        <button
          type="button"
          onClick={() => handleRun(true)}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700"
        >
          预演一轮
        </button>
        <button
          type="button"
          onClick={() => handleRun(false)}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700"
        >
          立即推送一轮
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

      {settings && (
        <div className="space-y-2 rounded border border-slate-200 p-3">
          <h2 className="text-sm font-semibold text-slate-700">推送设置</h2>
          <p className="text-sm text-slate-600">
            默认节奏：{settings.default_frequency === 'daily' ? '每天' : '每周'} · 单封上限：
            {settings.max_items_per_digest} 条 · 发送时间窗：{settings.send_window_start_hour}:00–
            {settings.send_window_end_hour}:00 · 重试上限：{settings.max_retries}
          </p>
          <p className="text-sm text-slate-600">
            当前状态：{settings.sends_paused ? '已暂停推送' : '正常推送'}
          </p>
          <button
            type="button"
            onClick={handleTogglePause}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700"
          >
            {settings.sends_paused ? '恢复推送' : '暂停推送'}
          </button>
        </div>
      )}

      {health && (
        <div className="space-y-2 rounded border border-slate-200 p-3">
          <h2 className="text-sm font-semibold text-slate-700">送达健康与合规自检</h2>
          <p className="text-sm text-slate-600">
            最近 {health.sampled} 条记录：成功 {health.sent}、失败 {health.failed}、失败率{' '}
            {(health.failure_rate * 100).toFixed(0)}%（阈值 {(health.threshold * 100).toFixed(0)}%）
          </p>
          <ul className="space-y-1 text-sm">
            {health.checklist.map((item) => (
              <li key={item.item} className="text-slate-600">
                <span aria-hidden>{item.ok ? '✅' : '⚠️'}</span> {item.item}：{item.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {subscriptions && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-700">
            订阅列表（共 {subscriptions.total}）
          </h2>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="py-1">邮箱</th>
                <th>状态</th>
                <th>节奏</th>
                <th>方向数</th>
                <th>最近发送</th>
              </tr>
            </thead>
            <tbody>
              {subscriptions.items.map((item) => (
                <tr key={item.id} className="border-t border-slate-100">
                  <td className="py-1">{item.email}</td>
                  <td>{STATUS_LABELS[item.status] ?? item.status}</td>
                  <td>{item.frequency === 'daily' ? '每天' : '每周'}</td>
                  <td>{item.topic_count}</td>
                  <td>{formatDate(item.last_sent_at)}</td>
                </tr>
              ))}
              {subscriptions.items.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-2 text-slate-400">
                    暂无订阅
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {digests && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-700">推送记录（共 {digests.total}）</h2>
          <ul className="space-y-1 text-sm">
            {digests.items.map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center gap-2 border-t border-slate-100 py-1"
              >
                <span className="text-slate-500">{formatDate(item.created_at)}</span>
                <span>{STATUS_LABELS[item.status] ?? item.status}</span>
                <span className="text-slate-500">{item.item_count} 篇</span>
                {item.error && <span className="text-red-600">{item.error}</span>}
                <button
                  type="button"
                  onClick={() => handleOpenDetail(item.id)}
                  className="text-xs text-brand-600 hover:underline"
                >
                  查看明细
                </button>
              </li>
            ))}
            {digests.items.length === 0 && <li className="py-2 text-slate-400">暂无推送记录</li>}
          </ul>
        </div>
      )}

      {detail && (
        <div className="space-y-2 rounded border border-slate-200 p-3">
          <h2 className="text-sm font-semibold text-slate-700">推送明细</h2>
          <ul className="space-y-1 text-sm">
            {detail.items.map((item) => (
              <li key={item.article_id} className="text-slate-600">
                {item.position}. {item.title}（命中：{item.matched_topics.join('、')}）
              </li>
            ))}
            {detail.items.length === 0 && <li className="text-slate-400">该周期无内容</li>}
          </ul>
        </div>
      )}
    </section>
  )
}
