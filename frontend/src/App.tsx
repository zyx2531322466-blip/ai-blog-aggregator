import { Link, Route, Routes } from 'react-router-dom'

import AdminEntryPlaceholder from './pages/AdminEntryPlaceholder'
import AdminInsightsPage from './pages/AdminInsightsPage'
import ArticleDetailPage from './pages/ArticleDetailPage'
import ArticleListPage from './pages/ArticleListPage'

/** 应用根组件：全站统一的页头 + 路由。 */
export default function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-semibold text-brand-700">
            博客聚合站
          </Link>
          <Link to="/admin" className="text-sm text-slate-600 hover:text-brand-700">
            管理后台
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6">
        <Routes>
          <Route path="/" element={<ArticleListPage />} />
          <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
          <Route path="/admin" element={<AdminInsightsPage />} />
          <Route path="/admin/sources" element={<AdminEntryPlaceholder title="来源配置" />} />
          <Route path="/admin/categories" element={<AdminEntryPlaceholder title="类别管理" />} />
          <Route path="/admin/dedup" element={<AdminEntryPlaceholder title="去重策略管理" />} />
        </Routes>
      </main>
    </div>
  )
}
