import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createWikiEntry,
  fetchAdminSubscriptions,
  fetchDeliveryHealth,
  fetchDigestDetail,
  fetchDigests,
  fetchKnowledgeDecisions,
  fetchKnowledgeStats,
  fetchNotificationSettings,
  fetchWikiEntries,
  overrideArticleKnowledge,
  retireWikiEntry,
  runDigests,
} from '../api/notifications'
import AdminNotificationsPage from './AdminNotificationsPage'
import AdminWikiPage from './AdminWikiPage'

vi.mock('../api/notifications', async () => {
  const actual =
    await vi.importActual<typeof import('../api/notifications')>('../api/notifications')
  return {
    ...actual,
    fetchAdminSubscriptions: vi.fn(),
    fetchDigests: vi.fn(),
    fetchDigestDetail: vi.fn(),
    runDigests: vi.fn(),
    fetchNotificationSettings: vi.fn(),
    updateNotificationSettings: vi.fn(),
    fetchDeliveryHealth: vi.fn(),
    fetchWikiEntries: vi.fn(),
    createWikiEntry: vi.fn(),
    retireWikiEntry: vi.fn(),
    fetchKnowledgeDecisions: vi.fn(),
    overrideArticleKnowledge: vi.fn(),
    fetchKnowledgeStats: vi.fn(),
  }
})

const mockedSubscriptions = vi.mocked(fetchAdminSubscriptions)
const mockedDigests = vi.mocked(fetchDigests)
const mockedDigestDetail = vi.mocked(fetchDigestDetail)
const mockedRunDigests = vi.mocked(runDigests)
const mockedSettings = vi.mocked(fetchNotificationSettings)
const mockedHealth = vi.mocked(fetchDeliveryHealth)
const mockedWikiEntries = vi.mocked(fetchWikiEntries)
const mockedCreateEntry = vi.mocked(createWikiEntry)
const mockedRetireEntry = vi.mocked(retireWikiEntry)
const mockedDecisions = vi.mocked(fetchKnowledgeDecisions)
const mockedOverride = vi.mocked(overrideArticleKnowledge)
const mockedStats = vi.mocked(fetchKnowledgeStats)

beforeEach(() => {
  vi.clearAllMocks()
  mockedSubscriptions.mockResolvedValue({
    total: 1,
    page: 1,
    page_size: 20,
    items: [
      {
        id: 'sub_1',
        email: 're****@example.com',
        status: 'confirmed',
        frequency: 'weekly',
        max_items: 10,
        topic_count: 2,
        last_sent_at: '2026-09-12T09:00:00Z',
        created_at: '2026-09-10T09:00:00Z',
      },
    ],
  })
  mockedDigests.mockResolvedValue({
    total: 1,
    page: 1,
    page_size: 20,
    items: [
      {
        id: 'digest_1',
        subscription_id: 'sub_1',
        period_start: '2026-09-07T00:00:00Z',
        period_end: '2026-09-14T00:00:00Z',
        status: 'sent',
        item_count: 2,
        retry_count: 0,
        sent_at: '2026-09-12T09:00:00Z',
        error: null,
        created_at: '2026-09-12T09:00:00Z',
      },
    ],
  })
  mockedDigestDetail.mockResolvedValue({
    id: 'digest_1',
    subscription_id: 'sub_1',
    period_start: '2026-09-07T00:00:00Z',
    period_end: '2026-09-14T00:00:00Z',
    status: 'sent',
    item_count: 1,
    retry_count: 0,
    sent_at: '2026-09-12T09:00:00Z',
    error: null,
    created_at: '2026-09-12T09:00:00Z',
    items: [
      {
        article_id: 'article_1',
        position: 1,
        matched_topics: ['类别：AI/机器学习'],
        title: '机器学习入门',
        url: 'https://a.example.com/1',
      },
    ],
  })
  mockedSettings.mockResolvedValue({
    default_frequency: 'weekly',
    max_items_per_digest: 10,
    send_window_start_hour: 9,
    send_window_end_hour: 21,
    send_empty_digest: false,
    max_retries: 3,
    sends_paused: false,
    bounce_pause_threshold: 0.05,
  })
  mockedHealth.mockResolvedValue({
    sampled: 4,
    sent: 3,
    failed: 1,
    skipped_empty: 0,
    failure_rate: 0.25,
    threshold: 0.5,
    paused: false,
    checklist: [
      { item: '真实发信开关', ok: false, detail: '当前为预演模式（只记录不投递）' },
      { item: '发信域名认证（SPF/DKIM/DMARC）', ok: false, detail: '需在域名侧配置' },
    ],
  })
  mockedWikiEntries.mockResolvedValue({
    total: 1,
    page: 1,
    page_size: 20,
    items: [
      {
        id: 'wiki_1',
        name: 'Raft 选主流程',
        summary: '任期选举',
        status: 'active',
        created_by: 'llm',
        merged_into_id: null,
        human_note: null,
        source_article_ids: ['article_1'],
        created_at: '2026-09-10T09:00:00Z',
        updated_at: '2026-09-10T09:00:00Z',
      },
    ],
  })
  mockedDecisions.mockResolvedValue({
    total: 1,
    page: 1,
    page_size: 20,
    items: [
      {
        id: 'kd_1',
        article_id: 'article_9',
        decision: 'covered',
        matched_entry_id: 'wiki_1',
        similarity: 0.95,
        rationale: '与条目相似度 0.95 ≥ 0.92，判定已被覆盖',
        points: [
          {
            name: 'Raft 选主流程',
            summary: '任期选举',
            is_new: false,
            similarity: 0.95,
            wiki_entry_id: null,
            matched_entry_id: 'wiki_1',
          },
        ],
        model: 'gpt-4o-mini',
        prompt_version: 'knowledge-v1',
        actor: 'system',
        created_at: '2026-09-12T09:00:00Z',
      },
    ],
  })
  mockedStats.mockResolvedValue({
    filtered_total: 3,
    by_category: { 'AI/机器学习': 3 },
    pending_total: 1,
    partial_total: 2,
    llm_usage: { calls_today: 5, failures_today: 1, tokens_today: 1200, records_total: 5 },
  })
})

function renderPage(element: React.ReactElement) {
  return render(<MemoryRouter>{element}</MemoryRouter>)
}

describe('AdminNotificationsPage', () => {
  it('令牌加载后展示订阅、推送记录、设置与合规自检', async () => {
    renderPage(<AdminNotificationsPage />)
    await userEvent.type(screen.getByLabelText('管理令牌'), 'token')
    await userEvent.click(screen.getByRole('button', { name: '加载' }))

    expect(await screen.findByText(/订阅列表（共 1）/)).toBeInTheDocument()
    expect(screen.getByText('re****@example.com')).toBeInTheDocument()
    expect(screen.getByText(/推送记录（共 1）/)).toBeInTheDocument()
    expect(screen.getByText(/发送时间窗：9:00–21:00/)).toBeInTheDocument()
    expect(screen.getByText(/SPF\/DKIM\/DMARC/)).toBeInTheDocument()
  })

  it('预演一轮只展示计划数量，不真实发送', async () => {
    mockedRunDigests.mockResolvedValue({
      dry_run: true,
      planned: [
        { subscription_id: 'sub_1', email: 're****@example.com', planned_items: 3, note: '可发送' },
      ],
      generated: 0,
      sent: 0,
      failed: 0,
      skipped_empty: 0,
    })
    renderPage(<AdminNotificationsPage />)
    await userEvent.type(screen.getByLabelText('管理令牌'), 'token')
    await userEvent.click(screen.getByRole('button', { name: '预演一轮' }))

    expect(await screen.findByText('预演完成：本次将推送 3 篇（未真实发送）')).toBeInTheDocument()
    expect(mockedRunDigests).toHaveBeenCalledWith('token', { dry_run: true })
  })

  it('查看推送明细展示命中方向', async () => {
    renderPage(<AdminNotificationsPage />)
    await userEvent.type(screen.getByLabelText('管理令牌'), 'token')
    await userEvent.click(screen.getByRole('button', { name: '加载' }))
    await screen.findByText(/推送记录（共 1）/)

    await userEvent.click(screen.getByRole('button', { name: '查看明细' }))

    expect(await screen.findByText(/命中：类别：AI\/机器学习/)).toBeInTheDocument()
  })

  it('鉴权失败时给出明确提示', async () => {
    mockedSettings.mockRejectedValue(new Error('UNAUTHORIZED'))
    renderPage(<AdminNotificationsPage />)
    await userEvent.type(screen.getByLabelText('管理令牌'), 'bad')
    await userEvent.click(screen.getByRole('button', { name: '加载' }))

    await waitFor(() => {
      expect(screen.getByText('鉴权失败，请检查管理令牌')).toBeInTheDocument()
    })
  })
})

describe('AdminWikiPage', () => {
  it('展示条目、判定记录与统计，并支持新增条目', async () => {
    mockedCreateEntry.mockResolvedValue({
      id: 'wiki_2',
      name: '日志压缩',
      summary: '',
      status: 'active',
      created_by: 'human',
      merged_into_id: null,
      human_note: null,
      source_article_ids: [],
      created_at: '2026-09-12T09:00:00Z',
      updated_at: '2026-09-12T09:00:00Z',
    })
    renderPage(<AdminWikiPage />)
    await userEvent.type(screen.getByLabelText('管理令牌'), 'token')
    await userEvent.click(screen.getByRole('button', { name: '加载' }))

    expect(await screen.findByText(/知识点条目（共 1）/)).toBeInTheDocument()
    expect(screen.getByText('Raft 选主流程')).toBeInTheDocument()
    expect(screen.getByText(/因知识重复被筛：3 篇/)).toBeInTheDocument()
    expect(screen.getByText(/判定记录（共 1）/)).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('知识点名称'), '日志压缩')
    await userEvent.click(screen.getByRole('button', { name: '新增' }))

    await waitFor(() => {
      expect(mockedCreateEntry).toHaveBeenCalledWith('token', { name: '日志压缩', summary: '' })
    })
    expect(await screen.findByText('知识点条目已创建')).toBeInTheDocument()
  })

  it('支持废止条目与改判文章', async () => {
    mockedRetireEntry.mockResolvedValue({
      id: 'wiki_1',
      name: 'Raft 选主流程',
      summary: '',
      status: 'retired',
      created_by: 'llm',
      merged_into_id: null,
      human_note: null,
      source_article_ids: [],
      created_at: '2026-09-10T09:00:00Z',
      updated_at: '2026-09-12T09:00:00Z',
    })
    mockedOverride.mockResolvedValue({
      id: 'kd_2',
      article_id: 'article_9',
      decision: 'new_knowledge',
      matched_entry_id: null,
      similarity: null,
      rationale: '维护者改判：该文包含新增信息',
      points: [],
      model: 'gpt-4o-mini',
      prompt_version: 'knowledge-v1',
      actor: 'human',
      created_at: '2026-09-12T10:00:00Z',
    })
    renderPage(<AdminWikiPage />)
    await userEvent.type(screen.getByLabelText('管理令牌'), 'token')
    await userEvent.click(screen.getByRole('button', { name: '加载' }))
    await screen.findByText(/知识点条目（共 1）/)

    await userEvent.click(screen.getByRole('button', { name: '废止' }))
    expect(await screen.findByText(/已废止「Raft 选主流程」/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '改判为全新知识' }))
    expect(await screen.findByText(/已改判为"全新知识"/)).toBeInTheDocument()
    expect(mockedOverride).toHaveBeenCalledWith('token', 'article_9', {
      decision: 'new_knowledge',
      reason: '维护者复核：该文包含新增信息',
    })
  })

  it('未填名称时不提交并提示', async () => {
    renderPage(<AdminWikiPage />)

    await userEvent.click(screen.getByRole('button', { name: '新增' }))

    expect(await screen.findByText('请填写知识点名称')).toBeInTheDocument()
    expect(mockedCreateEntry).not.toHaveBeenCalled()
  })
})
