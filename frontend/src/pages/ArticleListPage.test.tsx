import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchArticles } from '../api/articles'
import { fetchCategories } from '../api/categories'
import { fetchSources } from '../api/sources'
import type { ArticleListItem } from '../api/types'
import ArticleListPage from './ArticleListPage'

vi.mock('../api/articles', () => ({ fetchArticles: vi.fn() }))
vi.mock('../api/categories', () => ({ fetchCategories: vi.fn() }))
vi.mock('../api/sources', () => ({ fetchSources: vi.fn() }))

const mockedFetchArticles = vi.mocked(fetchArticles)
const mockedFetchCategories = vi.mocked(fetchCategories)
const mockedFetchSources = vi.mocked(fetchSources)

function makeArticle(overrides: Partial<ArticleListItem> = {}): ArticleListItem {
  return {
    id: 'article_1',
    title: '机器学习入门',
    summary: '介绍机器学习基础',
    category: ['AI/机器学习'],
    primary_category: { id: 'cat_ai', name: 'AI/机器学习' },
    tags: ['机器学习'],
    published_at: '2026-09-01T10:00:00Z',
    crawled_at: '2026-09-01T10:05:00Z',
    primary_source: { name: '站点A', url: 'https://a.example.com' },
    sources_count: 1,
    merged_sources_count: 0,
    status: 'normal',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedFetchCategories.mockResolvedValue([
    { name: 'AI/机器学习', article_count: 1 },
    { name: '数据库', article_count: 1 },
  ])
  mockedFetchArticles.mockResolvedValue({
    total: 1,
    page: 1,
    page_size: 10,
    items: [makeArticle()],
  })
  mockedFetchSources.mockResolvedValue([
    {
      id: 'source_1',
      name: '站点A',
      site_url: 'https://a.example.com',
      last_success_at: '2026-09-11T12:00:00Z',
      last_crawled_at: '2026-09-11T12:05:00Z',
    },
  ])
})

describe('ArticleListPage', () => {
  it('渲染文章列表字段', async () => {
    render(
      <MemoryRouter>
        <ArticleListPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('机器学习入门')).toBeInTheDocument()
    expect(screen.getByText('介绍机器学习基础')).toBeInTheDocument()
    expect(screen.getAllByText('站点A').length).toBeGreaterThan(0)
  })

  it('按类别筛选后使用 category 参数重新请求', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ArticleListPage />
      </MemoryRouter>,
    )
    await screen.findByText('机器学习入门')

    mockedFetchArticles.mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 10,
      items: [
        makeArticle({
          id: 'article_2',
          title: 'SQL 查询优化',
          primary_category: { id: 'cat_db', name: '数据库' },
        }),
      ],
    })

    await user.click(await screen.findByRole('button', { name: /数据库/ }))

    await waitFor(() =>
      expect(mockedFetchArticles).toHaveBeenLastCalledWith(
        expect.objectContaining({ category: '数据库', page: 1 }),
        expect.anything(),
      ),
    )
    expect(await screen.findByText('SQL 查询优化')).toBeInTheDocument()
  })

  it('展示合并来源数量', async () => {
    mockedFetchArticles.mockResolvedValue({
      total: 1,
      page: 1,
      page_size: 10,
      items: [makeArticle({ sources_count: 2, merged_sources_count: 1 })],
    })

    render(
      <MemoryRouter>
        <ArticleListPage />
      </MemoryRouter>,
    )

    expect(await screen.findByTestId('merged-count')).toHaveTextContent('共 2 个来源')
  })

  it('列表项同时展示发布时间与采集时间', async () => {
    render(
      <MemoryRouter>
        <ArticleListPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/发布于/)).toBeInTheDocument()
    expect(screen.getByText(/采集于/)).toBeInTheDocument()
  })

  it('展示来源更新状态与最后更新时间', async () => {
    render(
      <MemoryRouter>
        <ArticleListPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('来源更新状态')).toBeInTheDocument()
    expect(screen.getByText(/最后更新：/)).toBeInTheDocument()
  })
})
