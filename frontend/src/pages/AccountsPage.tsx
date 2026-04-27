import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchAccounts } from '../api/client'

export default function AccountsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['accounts'],
    queryFn: fetchAccounts,
  })

  if (isLoading) return <p className="text-gray-500">Loading accounts…</p>
  if (error) return <p className="text-red-600">Error: {String(error)}</p>

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-900 mb-4">Accounts</h1>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
        {data?.map((acc) => (
          <Link
            key={acc.account_id}
            to={`/account/${acc.account_id}`}
            className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-sm transition-all"
          >
            <div className="flex items-start justify-between">
              <span className="text-lg font-bold text-gray-900">{acc.account_id}</span>
              <span
                className={`text-xs px-1.5 py-0.5 rounded ${
                  acc.active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                }`}
              >
                {acc.active ? 'active' : 'inactive'}
              </span>
            </div>
            {acc.display_name && (
              <p className="text-sm text-gray-500 mt-1">{acc.display_name}</p>
            )}
            <p className="text-xs text-gray-400 mt-2">schema: {acc.schema_name}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}
