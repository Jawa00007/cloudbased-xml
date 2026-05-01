import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchAccounts } from '../api/client'

export default function AccountsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })

  if (isLoading) return <Skeleton />
  if (error) return <ErrorState msg={String(error)} />

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Accounts</h1>
        <p className="text-sm text-slate-500 mt-1">
          {data?.filter(a => a.active).length ?? 0} active accounts · {data?.length ?? 0} total
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {data?.map((acc) => (
          <Link
            key={acc.account_id}
            to={`/account/${acc.account_id}`}
            className="group bg-white rounded-2xl border border-slate-100 shadow-sm p-5 hover:border-blue-200 hover:shadow-md transition-all duration-150"
          >
            {/* Top row */}
            <div className="flex items-start justify-between mb-4">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold tracking-wide ${
                acc.active
                  ? 'bg-gradient-to-br from-blue-500 to-blue-700 text-white'
                  : 'bg-slate-100 text-slate-400'
              }`}>
                {acc.account_id.slice(0, 2).toUpperCase()}
              </div>
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ring-1 ring-inset ${
                acc.active
                  ? 'bg-emerald-50 text-emerald-700 ring-emerald-200'
                  : 'bg-slate-100 text-slate-400 ring-slate-200'
              }`}>
                {acc.active ? 'Active' : 'Off'}
              </span>
            </div>

            {/* Name */}
            <p className="font-semibold text-slate-900 text-sm leading-snug">{acc.account_id}</p>
            {acc.display_name && acc.display_name !== acc.account_id && (
              <p className="text-xs text-slate-400 mt-0.5 truncate">{acc.display_name}</p>
            )}

            {/* Arrow */}
            <div className="mt-4 flex items-center text-xs text-slate-400 group-hover:text-blue-500 transition-colors">
              <span>View PODs</span>
              <svg className="w-3.5 h-3.5 ml-1 group-hover:translate-x-0.5 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

function Skeleton() {
  return (
    <div>
      <div className="mb-8">
        <div className="h-7 w-28 bg-slate-200 rounded-lg animate-pulse mb-2" />
        <div className="h-4 w-52 bg-slate-100 rounded animate-pulse" />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-36 bg-slate-100 rounded-2xl animate-pulse" />
        ))}
      </div>
    </div>
  )
}

function ErrorState({ msg }: { msg: string }) {
  return (
    <div className="bg-red-50 border border-red-100 rounded-2xl p-6 text-sm text-red-700">
      <p className="font-medium mb-1">Failed to load accounts</p>
      <p className="text-xs text-red-500">{msg}</p>
    </div>
  )
}
