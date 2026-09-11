import type { PublicCategory } from '../api/categories'

interface CategoryFilterProps {
  categories: PublicCategory[]
  selected: string | null
  onSelect: (category: string | null) => void
}

const baseClass = 'rounded-full border px-3 py-1 text-sm transition-colors'
const activeClass = 'border-brand-600 bg-brand-600 text-white'
const inactiveClass = 'border-slate-300 bg-white text-slate-600 hover:border-brand-500'

/** 分类导航：全站统一的筛选交互。 */
export default function CategoryFilter({ categories, selected, onSelect }: CategoryFilterProps) {
  return (
    <nav aria-label="分类筛选" className="flex flex-wrap gap-2">
      <button
        type="button"
        aria-pressed={selected === null}
        onClick={() => onSelect(null)}
        className={`${baseClass} ${selected === null ? activeClass : inactiveClass}`}
      >
        全部
      </button>
      {categories.map((category) => (
        <button
          key={category.name}
          type="button"
          aria-pressed={selected === category.name}
          onClick={() => onSelect(category.name)}
          className={`${baseClass} ${selected === category.name ? activeClass : inactiveClass}`}
        >
          {category.name} ({category.article_count})
        </button>
      ))}
    </nav>
  )
}
