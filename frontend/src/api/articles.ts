import type { ArticleDetail, ArticleListResponse } from './types'

const API_BASE = '/api/v1/articles'

export interface ArticleQuery {
  category?: string
  tag?: string
  source?: string
  start_date?: string
  end_date?: string
  page?: number
  page_size?: number
}

function buildQuery(query: ArticleQuery): string {
  const params = new URLSearchParams()
  Object.entries(query).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  })
  return params.toString()
}

export async function fetchArticles(
  query: ArticleQuery = {},
  signal?: AbortSignal,
): Promise<ArticleListResponse> {
  const queryString = buildQuery(query)
  const url = queryString ? `${API_BASE}?${queryString}` : API_BASE
  const response = await fetch(url, { signal })
  if (!response.ok) {
    throw new Error(`文章列表加载失败: ${response.status}`)
  }
  return (await response.json()) as ArticleListResponse
}

export async function fetchArticle(
  articleId: string,
  signal?: AbortSignal,
): Promise<ArticleDetail> {
  const response = await fetch(`${API_BASE}/${encodeURIComponent(articleId)}`, { signal })
  if (!response.ok) {
    throw new Error(`文章详情加载失败: ${response.status}`)
  }
  return (await response.json()) as ArticleDetail
}
