import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchAccounts } from '../api/client'

export default function AccountsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })

  if (isLoading) return <Skeleton />
  if (error) return <Error msg={String(error)} />

  return (
    <div>
      <PageHeader title="Accounts" subtitle={`${data?.length ?? 0} active accounts`} />
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mt-6">
        {data?.map((acc) => (
          <Link
            key={acc.account_id}
            to={`/account/${acc.account_id}`}
            className="group bg-white rounded-xl border border-slate-200 p-4 hover:border-blue-300 hover:shadow-md transition-all"
          >
            <div className="flex items-start justify-between mb-3">
              <div className="w-9 h-9 bg-blue-50 rounded-lg flex items-center justify-center">
                <span className="text-blue-700 font-bold text-xs">{acc.account_id.slice(0, 2)}</span>
              </div>
              <span className={`text-xs px-1.5 py-0.5 rounded-md font-medium ring-1 ring-inset ${
                acc.active
                  ? 'bg-emerald-50 text-emerald-700 ring-emerald-200'
                  : 'bg-slate-100 text-slate-500 ring-slate-200'
              }`}>
                {acc.active ? 'active' : 'off'}
              </span>
            </div>
            <p className="font-semibold text-slate-900 text-sm">{acc.account_id}</p>
            {acc.display_name && acc.display_name !== acc.account_id && (
              <p className="text-xs text-slate-400 mt-0.5 truncate">{acc.display_name}</p>
            )}
            <p className="text-xs text-slate-300 mt-2">schema: {acc.schema_name}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}

function Skeleton() {
  return (
    <div>
      <div className="h-8 w-32 bg-slate-200 rounded animate-pulse mb-2" />
      <div className="h-4 w-48 bg-slate-100 rounded animate-pulse mb-6" />
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-28 bg-slate-100 rounded-xl animate-pulse" />
        ))}
      </div>
    </div>
  )
}

function Error({ msg }: { msg: string }) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">{msg}</div>
  )
}

function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
      {subtitle && <p className="text-sm text-slate-500 mt-0.5">{subtitle}</p>}
    </div>
  )
}
