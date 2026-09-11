export interface PublicCategory {
  name: string
  article_count: number
}

export async function fetchCategories(signal?: AbortSignal): Promise<PublicCategory[]> {
  const response = await fetch('/api/v1/categories', { signal })
  if (!response.ok) {
    throw new Error(`分类加载失败: ${response.status}`)
  }
  const body = (await response.json()) as { categories: PublicCategory[] }
  return body.categories
}
