export interface PublicSource {
  id: string
  name: string
  site_url: string
  last_success_at: string | null
  last_crawled_at: string | null
}

export async function fetchSources(signal?: AbortSignal): Promise<PublicSource[]> {
  const response = await fetch('/api/v1/sources', { signal })
  if (!response.ok) {
    throw new Error(`来源加载失败: ${response.status}`)
  }
  const body = (await response.json()) as { items: PublicSource[] }
  return body.items
}
