import type { SourceDetail } from '../api/types'
import { formatDate } from '../utils/format'

interface SourceListProps {
  sources: SourceDetail[]
}

/** 合并组来源列表：展示全部来源并支持跳转原文。 */
export default function SourceList({ sources }: SourceListProps) {
  return (
    <ul className="space-y-2">
      {sources.map((source) => (
        <li key={source.url} className="rounded border border-slate-200 bg-white p-3 text-sm">
          <div className="flex items-center gap-2">
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="text-brand-600 hover:underline"
            >
              {source.name ?? source.url}
            </a>
            {source.is_primary ? (
              <span className="rounded bg-brand-50 px-2 py-0.5 text-xs text-brand-700">主来源</span>
            ) : null}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            <span>采集时间：{formatDate(source.crawled_at)}</span>
            {source.published_at ? (
              <span className="ml-3">原文发布时间：{formatDate(source.published_at)}</span>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  )
}
