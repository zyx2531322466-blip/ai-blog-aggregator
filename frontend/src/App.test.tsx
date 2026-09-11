import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchArticle, fetchArticles } from './api/articles'
import { fetchCategories } from './api/categories'
import { fetchSources } from './api/sources'
import App from './App'

vi.mock('./api/articles', () => ({ fetchArticles: vi.fn(), fetchArticle: vi.fn() }))
vi.mock('./api/categories', () => ({ fetchCategories: vi.fn() }))
vi.mock('./api/sources', () => ({ fetchSources: vi.fn() }))

const mockedFetchArticles = vi.mocked(fetchArticles)
const mockedFetchArticle = vi.mocked(fetchArticle)
const mockedFetchCategories = vi.mocked(fetchCategories)
const mockedFetchSources = vi.mocked(fetchSources)

beforeEach(() => {
  vi.clearAllMocks()
  mockedFetchCategories.mockResolvedValue([{ name: 'Web 开发', article_count: 1 }])
  mockedFetchSources.mockResolvedValue([])
  mockedFetchArticles.mockResolvedValue({
    total: 1,
    page: 1,
    page_size: 10,
    items: [
      {
        id: 'article_1',
        title: 'React 前端实践',
        summary: '摘要',
        category: ['Web 开发'],
        primary_category: { id: 'cat_web', name: 'Web 开发' },
        tags: ['前端'],
        published_at: '2026-09-10T10:00:00Z',
        crawled_at: '2026-09-10T10:05:00Z',
        primary_source: { name: '站点 A', url: 'https://a.example.com' },
        sources_count: 1,
        merged_sources_count: 0,
        status: 'normal',
      },
    ],
  })
  mockedFetchArticle.mockResolvedValue({
    id: 'article_1',
    title: 'React 前端实践',
    content: '详情正文',
    summary: '摘要',
    category: ['Web 开发'],
    primary_category: { id: 'cat_web', name: 'Web 开发' },
    tags: ['前端'],
    published_at: '2026-09-10T10:00:00Z',
    crawled_at: '2026-09-10T10:05:00Z',
    sources: [
      {
        name: '站点 A',
        url: 'https://a.example.com',
        crawled_at: '2026-09-10T10:05:00Z',
        published_at: null,
        is_primary: true,
      },
    ],
    status: 'normal',
  })
})

describe('App 路由', () => {
  it('从列表页可进入详情页', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('link', { name: 'React 前端实践' }))

    expect(await screen.findByText('详情正文')).toBeInTheDocument()
    expect(mockedFetchArticle).toHaveBeenCalledWith('article_1', expect.anything())
  })

  it('可从页头进入管理后台概览页', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('link', { name: '管理后台' }))

    expect(await screen.findByText('维护者效果概览')).toBeInTheDocument()
  })
})
