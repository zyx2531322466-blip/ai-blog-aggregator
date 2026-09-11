interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onChange: (page: number) => void
}

/** 分页组件：统一的上一页/下一页交互。 */
export default function Pagination({ page, pageSize, total, onChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const buttonClass =
    'rounded border border-slate-300 px-3 py-1 text-sm disabled:cursor-not-allowed disabled:opacity-40'

  return (
    <nav aria-label="分页" className="flex items-center justify-center gap-4">
      <button
        type="button"
        onClick={() => onChange(page - 1)}
        disabled={page <= 1}
        className={buttonClass}
      >
        上一页
      </button>
      <span className="text-sm text-slate-600">
        第 {page} / {totalPages} 页
      </span>
      <button
        type="button"
        onClick={() => onChange(page + 1)}
        disabled={page >= totalPages}
        className={buttonClass}
      >
        下一页
      </button>
    </nav>
  )
}
