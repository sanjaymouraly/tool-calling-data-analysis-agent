import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  BarChart3,
  Database,
  History,
  LayoutDashboard,
  Menu,
  MessageSquareText,
  Moon,
  Settings,
  ShieldCheck,
  Sun,
  Wrench,
  X,
} from 'lucide-react'
import clsx from 'clsx'
import { useTheme } from '../hooks/useTheme'
import { Badge } from './ui'

const NAV_ITEMS = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/datasets', label: 'Datasets', icon: Database },
  { to: '/workspace', label: 'Analytics workspace', icon: MessageSquareText },
  { to: '/builder', label: 'Visual builder', icon: Wrench },
  { to: '/reports', label: 'Saved reports', icon: BarChart3 },
  { to: '/history', label: 'History', icon: History },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Layout({ children }: { children: ReactNode }) {
  const { theme, toggle } = useTheme()
  const [open, setOpen] = useState(false)
  const location = useLocation()

  useEffect(() => {
    setOpen(false)
  }, [location.pathname])

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white">
          <ShieldCheck size={19} />
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight">Data Analyst</p>
          <p className="truncate text-[11px] text-slate-500 dark:text-slate-400">
            Tool-calling agent · restricted tools
          </p>
        </div>
        <button
          type="button"
          className="ml-auto rounded p-1 text-slate-500 hover:bg-slate-100 md:hidden dark:hover:bg-slate-800"
          onClick={() => setOpen(false)}
          aria-label="Close navigation"
        >
          <X size={18} />
        </button>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200'
                  : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
              )
            }
          >
            <item.icon size={17} />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="space-y-2 border-t border-slate-200 p-4 text-[11px] text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <div className="flex items-center justify-between">
          <span>v1.0.0 · local mode</span>
          <Badge tone="emerald">no code execution</Badge>
        </div>
        <p>
          The model may only select from a fixed tool library. Every figure is computed server-side and
          cited back to a dataset hash.
        </p>
      </div>
    </div>
  )

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white md:block dark:border-slate-800 dark:bg-slate-900">
        {sidebar}
      </aside>

      {open ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-slate-900/50"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="relative h-full w-72 animate-slide-in border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            {sidebar}
          </div>
        </div>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white/80 px-4 py-3 backdrop-blur md:px-6 dark:border-slate-800 dark:bg-slate-900/80">
          <button
            type="button"
            className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 md:hidden dark:hover:bg-slate-800"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
          >
            <Menu size={18} />
          </button>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">
              {NAV_ITEMS.find((item) =>
                item.end ? location.pathname === item.to : location.pathname.startsWith(item.to),
              )?.label ?? 'Data Analyst'}
            </p>
          </div>
          <button
            type="button"
            onClick={toggle}
            className="rounded-lg border border-slate-200 p-2 text-slate-600 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto bg-slate-50 px-4 py-6 dark:bg-slate-950 md:px-6">
          <div className="mx-auto w-full max-w-[1400px]">{children}</div>
        </main>
      </div>
    </div>
  )
}
