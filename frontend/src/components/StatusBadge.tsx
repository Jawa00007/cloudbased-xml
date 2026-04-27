const MAP: Record<string, string> = {
  ok:        'bg-emerald-50 text-emerald-700 ring-emerald-200',
  error:     'bg-red-50 text-red-700 ring-red-200',
  skipped:   'bg-slate-100 text-slate-500 ring-slate-200',
  duplicate: 'bg-amber-50 text-amber-700 ring-amber-200',
  running:   'bg-blue-50 text-blue-700 ring-blue-200',
  E:         'bg-emerald-50 text-emerald-700 ring-emerald-200',
  S:         'bg-amber-50 text-amber-700 ring-amber-200',
  mixed:     'bg-orange-50 text-orange-700 ring-orange-200',
}

export default function StatusBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-slate-300">—</span>
  const cls = MAP[value] ?? 'bg-slate-100 text-slate-600 ring-slate-200'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ring-1 ring-inset ${cls}`}>
      {value}
    </span>
  )
}
