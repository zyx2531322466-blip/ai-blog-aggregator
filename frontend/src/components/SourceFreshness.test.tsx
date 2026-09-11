import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { PublicSource } from '../api/sources'
import SourceFreshness from './SourceFreshness'

const source: PublicSource = {
  id: 'source_1',
  name: '站点A',
  site_url: 'https://a.example',
  last_success_at: '2026-09-11T12:00:00Z',
  last_crawled_at: '2026-09-11T12:05:00Z',
}

describe('SourceFreshness', () => {
  it('展示来源名称与最后更新时间', () => {
    render(<SourceFreshness sources={[source]} />)

    expect(screen.getByText('站点A')).toBeInTheDocument()
    expect(screen.getByText(/最后更新：/)).toBeInTheDocument()
    expect(screen.getByText(/最后更新：/)).not.toHaveTextContent('未知时间')
  })

  it('无来源时展示占位提示', () => {
    render(<SourceFreshness sources={[]} />)

    expect(screen.getByText('暂无来源更新信息')).toBeInTheDocument()
  })

  it('缺少成功时间时回退到最近抓取时间', () => {
    render(
      <SourceFreshness
        sources={[{ ...source, last_success_at: null, last_crawled_at: '2026-09-10T08:00:00Z' }]}
      />,
    )

    expect(screen.getByText(/最后更新：/)).not.toHaveTextContent('未知时间')
  })
})
