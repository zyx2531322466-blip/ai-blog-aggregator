import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { PublicCategory } from '../api/categories'
import CategoryFilter from './CategoryFilter'

const categories: PublicCategory[] = [
  { name: 'AI/机器学习', article_count: 3 },
  { name: '数据库', article_count: 1 },
]

describe('CategoryFilter', () => {
  it('点击分类时回调对应类别名称', async () => {
    const onSelect = vi.fn()
    render(<CategoryFilter categories={categories} selected={null} onSelect={onSelect} />)

    await userEvent.click(screen.getByRole('button', { name: /数据库/ }))

    expect(onSelect).toHaveBeenCalledWith('数据库')
  })

  it('点击"全部"时回调 null', async () => {
    const onSelect = vi.fn()
    render(<CategoryFilter categories={categories} selected="数据库" onSelect={onSelect} />)

    await userEvent.click(screen.getByRole('button', { name: '全部' }))

    expect(onSelect).toHaveBeenCalledWith(null)
  })

  it('高亮当前选中的分类', () => {
    render(<CategoryFilter categories={categories} selected="数据库" onSelect={vi.fn()} />)

    expect(screen.getByRole('button', { name: /数据库/ })).toHaveAttribute('aria-pressed', 'true')
  })
})
