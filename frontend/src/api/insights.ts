export interface Insights {
  category_distribution: Record<string, number>
  dedup_stats: Record<string, number>
}

export async function fetchInsights(token: string, signal?: AbortSignal): Promise<Insights> {
  const response = await fetch('/api/v1/admin/insights', {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })
  if (response.status === 401) {
    throw new Error('UNAUTHORIZED')
  }
  if (!response.ok) {
    throw new Error(`概览加载失败: ${response.status}`)
  }
  return (await response.json()) as Insights
}
