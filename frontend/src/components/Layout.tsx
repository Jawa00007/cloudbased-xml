import { Link, useLocation } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'Accounts' },
  { to: '/files', label: 'File Log' },
  { to: '/sync', label: 'Sync' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 flex items-center gap-8 h-14">
          <span className="font-semibold text-gray-900 text-sm tracking-wide">
            SII Energy
          </span>
          <nav className="flex gap-1">
            {NAV.map(({ to, label }) => {
              const active = pathname === to || (to !== '/' && pathname.startsWith(to))
              return (
                <Link
                  key={to}
                  to={to}
                  className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                    active
                      ? 'bg-blue-50 text-blue-700'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  }`}
                >
                  {label}
                </Link>
              )
            })}
          </nav>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 py-6">{children}</main>
    </div>
  )
}
