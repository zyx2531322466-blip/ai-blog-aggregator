import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchArticle } from '../api/articles'
import type { ArticleDetail } from '../api/types'
import ArticleDetailPage from './ArticleDetailPage'

vi.mock('../api/articles', () => ({ fetchArticle: vi.fn() }))

const mockedFetchArticle = vi.mocked(fetchArticle)

const mergedDetail: ArticleDetail = {
  id: 'article_1',
  title: 'React 前端实践',
  content: '正文内容',
  summary: '摘要',
  category: ['Web 开发'],
  primary_category: { id: 'cat_web', name: 'Web 开发' },
  tags: ['前端'],
  published_at: '2026-09-10T10:00:00Z',
  crawled_at: '2026-09-10T10:05:00Z',
  sources: [
    {
      name: '站点 A',
      url: 'https://a.example.com/react',
      crawled_at: '2026-09-10T10:05:00Z',
      published_at: '2026-09-10T10:00:00Z',
      is_primary: true,
    },
    {
      name: '站点 B',
      url: 'https://b.example.com/react-copy',
      crawled_at: '2026-09-11T10:05:00Z',
      published_at: null,
      is_primary: false,
    },
  ],
  status: 'normal',
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/articles/article_1']}>
      <Routes>
        <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedFetchArticle.mockResolvedValue(mergedDetail)
})

describe('ArticleDetailPage', () => {
  it('展示正文、时间与全部合并来源', async () => {
    renderDetail()

    expect(await screen.findByText('React 前端实践')).toBeInTheDocument()
    expect(screen.getByText('正文内容')).toBeInTheDocument()
    expect(screen.getByText('站点 A')).toBeInTheDocument()
    expect(screen.getByText('站点 B')).toBeInTheDocument()
    expect(screen.getByText('来源（2）')).toBeInTheDocument()
    expect(screen.getByText('主来源')).toBeInTheDocument()
    // T19：详情页同时展示原文发布时间与采集时间
    expect(screen.getAllByText(/原文发布时间：/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/采集时间：/).length).toBeGreaterThan(0)
  })

  it('来源链接指向原文并可新窗口打开', async () => {
    renderDetail()

    const link = await screen.findByRole('link', { name: '站点 B' })
    expect(link).toHaveAttribute('href', 'https://b.example.com/react-copy')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('请求失败时展示错误提示', async () => {
    mockedFetchArticle.mockRejectedValue(new Error('boom'))
    renderDetail()

    expect(await screen.findByText('文章加载失败，请稍后重试')).toBeInTheDocument()
  })
})
