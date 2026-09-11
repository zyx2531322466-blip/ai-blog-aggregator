import type { PublicSource } from '../api/sources'
import { formatDate } from '../utils/format'

interface SourceFreshnessProps {
  sources: PublicSource[]
}

/** 来源维度新鲜度：展示每个来源的最后一次成功更新时间（T19）。 */
export default function SourceFreshness({ sources }: SourceFreshnessProps) {
  if (sources.length === 0) {
    return <p className="text-sm text-slate-500">暂无来源更新信息</p>
  }

  return (
    <ul className="space-y-1 text-sm text-slate-600">
      {sources.map((source) => (
        <li key={source.id} className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-slate-700">{source.name}</span>
          <span>最后更新：{formatDate(source.last_success_at ?? source.last_crawled_at)}</span>
        </li>
      ))}
    </ul>
  )
}
