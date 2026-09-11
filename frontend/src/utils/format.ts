const UNKNOWN_TIME = '未知时间'

/** 统一的日期展示格式（全站一致，见 constitution.md「内容呈现一致性」）。 */
export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return UNKNOWN_TIME
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return UNKNOWN_TIME
  }
  return date.toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
}
