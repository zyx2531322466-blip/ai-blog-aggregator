export interface CategoryRef {
  id: string
  name: string
}

export interface SourceSummary {
  name: string
  url: string
}

export interface ArticleListItem {
  id: string
  title: string
  summary: string | null
  category: string[]
  primary_category: CategoryRef | null
  tags: string[]
  published_at: string | null
  crawled_at: string
  primary_source: SourceSummary | null
  sources_count: number
  merged_sources_count: number
  status: string
}

export interface ArticleListResponse {
  total: number
  page: number
  page_size: number
  items: ArticleListItem[]
}

export interface SourceDetail {
  name: string | null
  url: string
  crawled_at: string | null
  published_at: string | null
  is_primary: boolean
}

export interface ArticleDetail {
  id: string
  title: string
  content: string
  summary: string | null
  category: string[]
  primary_category: CategoryRef | null
  tags: string[]
  published_at: string | null
  crawled_at: string
  sources: SourceDetail[]
  status: string
}
