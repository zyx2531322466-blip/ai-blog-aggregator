import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { confirmSubscription, fetchMySubscription, unsubscribe } from '../api/subscriptions'
import SubscriptionConfirmPage from './SubscriptionConfirmPage'
import SubscriptionUnsubscribePage from './SubscriptionUnsubscribePage'

vi.mock('../api/subscriptions', () => ({
  confirmSubscription: vi.fn(),
  fetchMySubscription: vi.fn(),
  unsubscribe: vi.fn(),
}))

const mockedConfirm = vi.mocked(confirmSubscription)
const mockedFetchMe = vi.mocked(fetchMySubscription)
const mockedUnsubscribe = vi.mocked(unsubscribe)

beforeEach(() => {
  vi.clearAllMocks()
})

function renderWithRoute(path: string, element: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={path.split('?')[0]} element={element} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SubscriptionConfirmPage', () => {
  it('带凭证访问时完成确认', async () => {
    mockedConfirm.mockResolvedValue({ status: 'confirmed' })
    renderWithRoute('/subscriptions/confirm?token=abc12345', <SubscriptionConfirmPage />)

    expect(await screen.findByText(/订阅已确认/)).toBeInTheDocument()
    expect(mockedConfirm).toHaveBeenCalledWith('abc12345')
  })

  it('凭证无效时展示服务端原因并提供重新订阅入口', async () => {
    mockedConfirm.mockRejectedValue(new Error('确认链接已过期，请重新发起订阅'))
    renderWithRoute('/subscriptions/confirm?token=expired-token', <SubscriptionConfirmPage />)

    expect(await screen.findByText('确认链接已过期，请重新发起订阅')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '重新发起订阅' })).toBeInTheDocument()
  })

  it('缺少凭证时直接提示', async () => {
    renderWithRoute('/subscriptions/confirm', <SubscriptionConfirmPage />)

    expect(await screen.findByText(/缺少确认凭证/)).toBeInTheDocument()
    expect(mockedConfirm).not.toHaveBeenCalled()
  })
})

describe('SubscriptionUnsubscribePage', () => {
  it('展示订阅信息并支持退订单个订阅', async () => {
    mockedFetchMe.mockResolvedValue({
      id: 'sub_1',
      email: 're****@example.com',
      status: 'confirmed',
      frequency: 'weekly',
      max_items: 10,
      created_at: '2026-09-10T10:00:00Z',
      topics: [{ type: 'category', value: 'AI/机器学习' }],
    })
    mockedUnsubscribe.mockResolvedValue({ status: 'unsubscribed', affected: 1 })
    renderWithRoute('/subscriptions/unsubscribe?token=abc12345', <SubscriptionUnsubscribePage />)

    expect(await screen.findByText(/re\*\*\*\*@example.com/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '退订该订阅' }))

    expect(await screen.findByText('已退订该订阅，不会再收到推送')).toBeInTheDocument()
    expect(mockedUnsubscribe).toHaveBeenCalledWith('abc12345', 'self')
  })

  it('支持退订该邮箱的全部订阅', async () => {
    mockedFetchMe.mockResolvedValue({
      id: 'sub_1',
      email: 're****@example.com',
      status: 'confirmed',
      frequency: 'daily',
      max_items: 5,
      created_at: '2026-09-10T10:00:00Z',
      topics: [{ type: 'keyword', value: '向量数据库' }],
    })
    mockedUnsubscribe.mockResolvedValue({ status: 'unsubscribed', affected: 3 })
    renderWithRoute('/subscriptions/unsubscribe?token=abc12345', <SubscriptionUnsubscribePage />)

    await screen.findByText(/re\*\*\*\*@example.com/)
    await userEvent.click(screen.getByRole('button', { name: '退订该邮箱的全部订阅' }))

    expect(await screen.findByText('已退订该邮箱的全部订阅（共 3 条）')).toBeInTheDocument()
    expect(mockedUnsubscribe).toHaveBeenCalledWith('abc12345', 'all')
  })

  it('凭证无效时提示使用最新邮件链接', async () => {
    mockedFetchMe.mockRejectedValue(new Error('凭证无效'))
    renderWithRoute('/subscriptions/unsubscribe?token=stale', <SubscriptionUnsubscribePage />)

    expect(await screen.findByText('凭证无效')).toBeInTheDocument()
  })
})
