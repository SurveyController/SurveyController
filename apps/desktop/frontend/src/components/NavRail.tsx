import { type MouseEvent } from 'react'
import {
  CircleEllipsis,
  CircleHelp,
  FileText,
  GitBranch,
  Home,
  MessageCircle,
  RefreshCcw,
  Settings,
  SlidersHorizontal,
  type LucideIcon,
} from 'lucide-react'
import { NavBarLink } from 'react-windows-ui'
import type { NavItem } from '../types'

interface NavRailProps {
  topNav: NavItem[]
  bottomNav: NavItem[]
  currentPage: string
  onChange: (page: string) => void
}

const icons: Record<string, LucideIcon> = {
  home: Home,
  settings: SlidersHorizontal,
  flow: GitBranch,
  refresh: RefreshCcw,
  document: CircleHelp,
  chat: MessageCircle,
  sliders: Settings,
  grid: CircleEllipsis,
}

function NavRail({ topNav, bottomNav, currentPage, onChange }: NavRailProps) {
  return (
    <aside className="side-nav">
      <nav className="side-nav-list">
        <ul className="side-nav-section">
          {topNav.map((item) => (
            <NavButton key={item.id} item={item} active={currentPage === item.id} onClick={() => onChange(item.id)} />
          ))}
        </ul>
        <ul className="side-nav-section">
          {bottomNav.map((item) => (
            <NavButton key={item.id} item={item} active={currentPage === item.id} onClick={() => onChange(item.id)} />
          ))}
        </ul>
      </nav>
    </aside>
  )
}

function NavButton({ item, active, onClick }: { item: NavItem, active: boolean, onClick: () => void }) {
  const Icon = icons[item.icon] ?? FileText
  return (
    <NavBarLink
      href="#"
      text={item.label}
      icon={<Icon size={21} strokeWidth={2} />}
      active={active}
      showBadge={item.badge}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        event.preventDefault()
        onClick()
      }}
    />
  )
}

export default NavRail
