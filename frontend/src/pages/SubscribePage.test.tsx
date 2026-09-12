import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createSubscription, fetchTopicOptions } from '../api/subscriptions'
import SubscribePage from './SubscribePage'

vi.mock('../api/subscriptions', () => ({
  fetchTopicOptions: vi.fn(),
  createSubscription: vi.fn(),
}))

const mockedFetchTopicOptions = vi.mocked(fetchTopicOptions)
const mockedCreateSubscription = vi.mocked(createSubscription)

beforeEach(() => {
  vi.clearAllMocks()
  mockedFetchTopicOptions.mockResolvedValue({
    categories: [{ value: 'AI/机器学习' }],
    tags: [{ value: 'Kubernetes' }],
    sources: [{ value: 'source_1', name: '示例博客', site_url: 'https://blog.example.com/' }],
    frequencies: ['daily', 'weekly'],
  })
})

function renderPage() {
  return render(
    <MemoryRouter>
      <SubscribePage />
    </MemoryRouter>,
  )
}

describe('SubscribePage', () => {
  it('渲染可选方向与节奏，并披露外部 LLM 数据边界', async () => {
    renderPage()

    expect(await screen.findByRole('button', { name: /类别：AI\/机器学习/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /标签：Kubernetes/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /来源：示例博客/ })).toBeInTheDocument()
    expect(screen.getByLabelText('推送节奏')).toBeInTheDocument()
    expect(screen.getByText(/你的邮箱不会参与该过程/)).toBeInTheDocument()
  })

  it('未填邮箱或未选方向时给出校验提示', async () => {
    renderPage()
    await screen.findByRole('button', { name: /类别：AI\/机器学习/ })

    await userEvent.click(screen.getByRole('button', { name: '提交订阅' }))
    expect(screen.getByText('请填写正确的邮箱地址')).toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('邮箱'), 'reader@example.com')
    await userEvent.click(screen.getByRole('button', { name: '提交订阅' }))
    expect(screen.getByText('请至少选择一个订阅方向')).toBeInTheDocument()
    expect(mockedCreateSubscription).not.toHaveBeenCalled()
  })

  it('提交成功后进入"请查收确认邮件"状态', async () => {
    mockedCreateSubscription.mockResolvedValue({
      id: 'sub_1',
      status: 'pending_confirmation',
      confirm_expires_at: '2026-09-15T10:00:00Z',
      message: '确认邮件已发送，请在有效期内点击邮件中的确认链接',
    })
    renderPage()
    await screen.findByRole('button', { name: /类别：AI\/机器学习/ })

    await userEvent.click(screen.getByRole('button', { name: /类别：AI\/机器学习/ }))
    await userEvent.type(screen.getByLabelText('邮箱'), 'reader@example.com')
    await userEvent.click(screen.getByRole('button', { name: '提交订阅' }))

    expect(await screen.findByRole('heading', { name: '请查收确认邮件' })).toBeInTheDocument()
    expect(screen.getByText(/只有点击邮件中的确认链接后，订阅才会生效/)).toBeInTheDocument()
    expect(mockedCreateSubscription).toHaveBeenCalledWith(
      expect.objectContaining({
        email: 'reader@example.com',
        topics: [{ type: 'category', value: 'AI/机器学习' }],
        frequency: 'weekly',
      }),
    )
  })

  it('可以添加关键词方向', async () => {
    renderPage()
    await screen.findByRole('button', { name: /类别：AI\/机器学习/ })

    await userEvent.type(screen.getByLabelText('关键词'), '向量数据库')
    await userEvent.click(screen.getByRole('button', { name: '添加关键词' }))

    expect(screen.getByText(/已选择（1）/)).toBeInTheDocument()
    expect(screen.getByText('关键词：向量数据库')).toBeInTheDocument()
  })

  it('后端返回错误时展示原因', async () => {
    mockedCreateSubscription.mockRejectedValue(new Error('该邮箱已订阅相同方向'))
    renderPage()
    await screen.findByRole('button', { name: /类别：AI\/机器学习/ })

    await userEvent.click(screen.getByRole('button', { name: /标签：Kubernetes/ }))
    await userEvent.type(screen.getByLabelText('邮箱'), 'reader@example.com')
    await userEvent.click(screen.getByRole('button', { name: '提交订阅' }))

    expect(await screen.findByText('该邮箱已订阅相同方向')).toBeInTheDocument()
  })

  it('方向清单加载失败时给出提示', async () => {
    mockedFetchTopicOptions.mockRejectedValue(new Error('boom'))
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('订阅方向加载失败，请稍后重试')).toBeInTheDocument()
    })
  })
})
