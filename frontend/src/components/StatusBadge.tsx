const MAP: Record<string, string> = {
  ok: 'bg-green-100 text-green-800',
  error: 'bg-red-100 text-red-800',
  skipped: 'bg-gray-100 text-gray-600',
  duplicate: 'bg-yellow-100 text-yellow-800',
  running: 'bg-blue-100 text-blue-700',
  E: 'bg-green-100 text-green-800',
  S: 'bg-yellow-100 text-yellow-800',
  mixed: 'bg-orange-100 text-orange-800',
}

export default function StatusBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-gray-400">—</span>
  const cls = MAP[value] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {value}
    </span>
  )
}
