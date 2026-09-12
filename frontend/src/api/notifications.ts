/** 维护者：推送记录、推送设置、知识 Wiki 与知识判定的接口封装（T24–T26）。 */

const BASE = '/api/v1'

export class UnauthorizedError extends Error {
  constructor() {
    super('UNAUTHORIZED')
  }
}

async function request<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init?.headers ?? {}),
    },
  })
  if (response.status === 401 || response.status === 403) {
    throw new UnauthorizedError()
  }
  if (!response.ok) {
    let message = `请求失败: ${response.status}`
    try {
      const body = (await response.json()) as { error?: { message?: string } }
      message = body.error?.message ?? message
    } catch {
      /* 忽略解析失败，沿用默认提示 */
    }
    throw new Error(message)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

// ---------------------------------------------------------------------------
// 推送记录与设置
// ---------------------------------------------------------------------------

export interface AdminSubscription {
  id: string
  email: string
  status: string
  frequency: string
  max_items: number
  topic_count: number
  last_sent_at: string | null
  created_at: string
}

export interface AdminSubscriptionList {
  total: number
  page: number
  page_size: number
  items: AdminSubscription[]
}

export interface DigestRecord {
  id: string
  subscription_id: string
  period_start: string
  period_end: string
  status: string
  item_count: number
  retry_count: number
  sent_at: string | null
  error: string | null
  created_at: string
}

export interface DigestItem {
  article_id: string
  position: number
  matched_topics: string[]
  title: string
  url: string
}

export interface DigestDetail extends DigestRecord {
  items: DigestItem[]
}

export interface DigestList {
  total: number
  page: number
  page_size: number
  items: DigestRecord[]
}

export interface NotificationSettings {
  default_frequency: string
  max_items_per_digest: number
  send_window_start_hour: number
  send_window_end_hour: number
  send_empty_digest: boolean
  max_retries: number
  sends_paused: boolean
  bounce_pause_threshold: number
}

export interface DigestRunResult {
  dry_run: boolean
  planned: { subscription_id: string; email: string; planned_items: number; note: string }[]
  generated: number
  sent: number
  failed: number
  skipped_empty: number
}

export interface DeliveryHealth {
  sampled: number
  sent: number
  failed: number
  skipped_empty: number
  failure_rate: number
  threshold: number
  paused: boolean
  checklist: { item: string; ok: boolean; detail?: string | null }[]
}

export function fetchAdminSubscriptions(
  token: string,
  params: { status?: string; frequency?: string } = {},
): Promise<AdminSubscriptionList> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.frequency) query.set('frequency', params.frequency)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return request<AdminSubscriptionList>(`/admin/subscriptions${suffix}`, token)
}

export function fetchDigests(token: string, status?: string): Promise<DigestList> {
  const suffix = status ? `?status=${encodeURIComponent(status)}` : ''
  return request<DigestList>(`/admin/digests${suffix}`, token)
}

export function fetchDigestDetail(token: string, digestId: string): Promise<DigestDetail> {
  return request<DigestDetail>(`/admin/digests/${encodeURIComponent(digestId)}`, token)
}

export function runDigests(
  token: string,
  payload: { subscription_id?: string; dry_run?: boolean } = {},
): Promise<DigestRunResult> {
  return request<DigestRunResult>('/admin/digests/run', token, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchNotificationSettings(token: string): Promise<NotificationSettings> {
  return request<NotificationSettings>('/admin/notification-settings', token)
}

export function updateNotificationSettings(
  token: string,
  changes: Partial<NotificationSettings>,
): Promise<NotificationSettings> {
  return request<NotificationSettings>('/admin/notification-settings', token, {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })
}

export function fetchDeliveryHealth(token: string): Promise<DeliveryHealth> {
  return request<DeliveryHealth>('/admin/delivery-health', token)
}

// ---------------------------------------------------------------------------
// 知识 Wiki 与判定复核
// ---------------------------------------------------------------------------

export interface WikiEntry {
  id: string
  name: string
  summary: string
  status: string
  created_by: string
  merged_into_id: string | null
  human_note: string | null
  source_article_ids: string[]
  created_at: string
  updated_at: string
}

export interface WikiEntryList {
  total: number
  page: number
  page_size: number
  items: WikiEntry[]
}

export interface WikiEntryInput {
  name: string
  summary?: string
  article_ids?: string[]
  note?: string
}

export interface KnowledgeDecision {
  id: string
  article_id: string
  decision: string
  matched_entry_id: string | null
  similarity: number | null
  rationale: string | null
  points: {
    name: string
    summary: string
    is_new: boolean
    similarity: number
    wiki_entry_id: string | null
    matched_entry_id: string | null
  }[]
  model: string | null
  prompt_version: string | null
  actor: string
  created_at: string
}

export interface KnowledgeDecisionList {
  total: number
  page: number
  page_size: number
  items: KnowledgeDecision[]
}

export interface KnowledgeStats {
  filtered_total: number
  by_category: Record<string, number>
  pending_total: number
  partial_total: number
  llm_usage: {
    calls_today: number
    failures_today: number
    tokens_today: number
    records_total: number
  }
}

export function fetchWikiEntries(
  token: string,
  params: { status?: string; query?: string } = {},
): Promise<WikiEntryList> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.query) query.set('query', params.query)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return request<WikiEntryList>(`/admin/wiki/entries${suffix}`, token)
}

export function createWikiEntry(token: string, payload: WikiEntryInput): Promise<WikiEntry> {
  return request<WikiEntry>('/admin/wiki/entries', token, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateWikiEntry(
  token: string,
  entryId: string,
  payload: Partial<WikiEntryInput>,
): Promise<WikiEntry> {
  return request<WikiEntry>(`/admin/wiki/entries/${encodeURIComponent(entryId)}`, token, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function retireWikiEntry(token: string, entryId: string): Promise<WikiEntry> {
  return request<WikiEntry>(`/admin/wiki/entries/${encodeURIComponent(entryId)}/retire`, token, {
    method: 'POST',
  })
}

export function mergeWikiEntries(
  token: string,
  payload: { source_entry_ids: string[]; name: string; summary?: string },
): Promise<WikiEntry> {
  return request<WikiEntry>('/admin/wiki/entries/merge', token, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchKnowledgeDecisions(
  token: string,
  params: { decision?: string } = {},
): Promise<KnowledgeDecisionList> {
  const suffix = params.decision ? `?decision=${encodeURIComponent(params.decision)}` : ''
  return request<KnowledgeDecisionList>(`/admin/knowledge-decisions${suffix}`, token)
}

export function overrideArticleKnowledge(
  token: string,
  articleId: string,
  payload: { decision: string; reason: string },
): Promise<KnowledgeDecision> {
  return request<KnowledgeDecision>(
    `/admin/articles/${encodeURIComponent(articleId)}/knowledge-override`,
    token,
    { method: 'POST', body: JSON.stringify(payload) },
  )
}

export function fetchKnowledgeStats(token: string): Promise<KnowledgeStats> {
  return request<KnowledgeStats>('/admin/knowledge-stats', token)
}
