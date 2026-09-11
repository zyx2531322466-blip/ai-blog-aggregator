import { Link } from 'react-router-dom'

/** 各管理子入口的占位页：具体子功能由 T04/T07/T15 的后端接口提供。 */
export default function AdminEntryPlaceholder({ title }: { title: string }) {
  return (
    <section className="space-y-3">
      <Link to="/admin" className="text-sm text-brand-600 hover:underline">
        ← 返回概览
      </Link>
      <h1 className="text-xl font-semibold text-slate-800">{title}</h1>
      <p className="text-sm text-slate-500">
        该管理入口对应的后端能力已在对应 Ticket 中实现（T04 来源配置 / T07 类别管理 / T15
        去重策略）。
      </p>
    </section>
  )
}
