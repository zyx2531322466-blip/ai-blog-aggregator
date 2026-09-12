/** 订阅相关接口封装（T22/T23）：方向清单、创建订阅、确认、退订、自助查询。 */

export interface TopicOption {
  value: string
  name?: string | null
  site_url?: string | null
}

export interface TopicOptions {
  categories: TopicOption[]
  tags: TopicOption[]
  sources: TopicOption[]
  frequencies: string[]
}

export interface SubscriptionTopicInput {
  type: 'category' | 'tag' | 'source' | 'keyword'
  value: string
}

export interface SubscriptionCreatePayload {
  email: string
  topics: SubscriptionTopicInput[]
  frequency?: string
  max_items?: number
}

export interface SubscriptionCreated {
  id: string
  status: string
  confirm_expires_at: string
  message: string
}

export interface SubscriptionMe {
  id: string
  email: string
  status: string
  frequency: string
  max_items: number
  created_at: string
  topics: { type: string; value: string }[]
}

const BASE = '/api/v1'

async function readError(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { message?: string } }
    return body.error?.message ?? fallback
  } catch {
    return fallback
  }
}

export async function fetchTopicOptions(signal?: AbortSignal): Promise<TopicOptions> {
  const response = await fetch(`${BASE}/subscription-topics`, { signal })
  if (!response.ok) {
    throw new Error(`订阅方向加载失败: ${response.status}`)
  }
  return (await response.json()) as TopicOptions
}

export async function createSubscription(
  payload: SubscriptionCreatePayload,
): Promise<SubscriptionCreated> {
  const response = await fetch(`${BASE}/subscriptions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await readError(response, '订阅失败，请稍后再试'))
  }
  return (await response.json()) as SubscriptionCreated
}

export async function confirmSubscription(token: string): Promise<{ status: string }> {
  const response = await fetch(`${BASE}/subscriptions/confirm?token=${encodeURIComponent(token)}`)
  if (!response.ok) {
    throw new Error(await readError(response, '确认链接无效或已过期'))
  }
  return (await response.json()) as { status: string }
}

export async function unsubscribe(
  token: string,
  scope: 'self' | 'all' = 'self',
): Promise<{ status: string; affected: number }> {
  const response = await fetch(`${BASE}/subscriptions/unsubscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, scope }),
  })
  if (!response.ok) {
    throw new Error(await readError(response, '退订失败，请使用最新的邮件链接'))
  }
  return (await response.json()) as { status: string; affected: number }
}

export async function fetchMySubscription(token: string): Promise<SubscriptionMe> {
  const response = await fetch(`${BASE}/subscriptions/me?token=${encodeURIComponent(token)}`)
  if (!response.ok) {
    throw new Error(await readError(response, '订阅信息加载失败'))
  }
  return (await response.json()) as SubscriptionMe
}

export async function deleteSubscription(token: string): Promise<void> {
  const response = await fetch(`${BASE}/subscriptions/me`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, scope: 'self' }),
  })
  if (!response.ok && response.status !== 204) {
    throw new Error(await readError(response, '删除订阅失败'))
  }
}
