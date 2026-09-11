import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchInsights } from '../api/insights'
import AdminInsightsPage from './AdminInsightsPage'

vi.mock('../api/insights', () => ({ fetchInsights: vi.fn() }))

const mockedFetchInsights = vi.mocked(fetchInsights)

beforeEach(() => {
  vi.clearAllMocks()
  mockedFetchInsights.mockResolvedValue({
    category_distribution: { 'AI/机器学习': 2, 数据库: 1, 未分类: 1 },
    dedup_stats: {
      exact_duplicate: 1,
      near_duplicate: 0,
      related: 1,
      merged_duplicates: 1,
      total_articles: 5,
      unique_articles: 4,
    },
  })
})

describe('AdminInsightsPage', () => {
  it('加载并展示分类分布与去重统计', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <AdminInsightsPage />
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText('管理令牌'), 'test-admin-token')
    await user.click(screen.getByRole('button', { name: '加载概览' }))

    expect(await screen.findByTestId('category-AI/机器学习')).toHaveTextContent('2')
    expect(screen.getByTestId('dedup-exact_duplicate')).toHaveTextContent('1')
    expect(screen.getByTestId('dedup-related')).toHaveTextContent('1')
    expect(screen.getByTestId('dedup-unique_articles')).toHaveTextContent('4')
    expect(screen.getByText('完全重复')).toBeInTheDocument()
    expect(mockedFetchInsights).toHaveBeenCalledWith('test-admin-token')
  })

  it('提供来源/类别/去重策略管理入口链接', () => {
    render(
      <MemoryRouter>
        <AdminInsightsPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('link', { name: '来源配置' })).toHaveAttribute('href', '/admin/sources')
    expect(screen.getByRole('link', { name: '类别管理' })).toHaveAttribute(
      'href',
      '/admin/categories',
    )
    expect(screen.getByRole('link', { name: '去重策略管理' })).toHaveAttribute(
      'href',
      '/admin/dedup',
    )
  })

  it('鉴权失败时展示提示', async () => {
    const user = userEvent.setup()
    mockedFetchInsights.mockRejectedValue(new Error('UNAUTHORIZED'))
    render(
      <MemoryRouter>
        <AdminInsightsPage />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: '加载概览' }))

    expect(await screen.findByText('鉴权失败，请检查管理令牌')).toBeInTheDocument()
  })
})
