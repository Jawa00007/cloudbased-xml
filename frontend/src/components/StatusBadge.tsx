const MAP: Record<string, { cls: string; dot?: boolean }> = {
  ok:        { cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200', dot: true },
  error:     { cls: 'bg-red-50 text-red-600 ring-red-200',   dot: true },
  skipped:   { cls: 'bg-slate-100 text-slate-500 ring-slate-200' },
  duplicate: { cls: 'bg-amber-50 text-amber-700 ring-amber-200' },
  running:   { cls: 'bg-blue-50 text-blue-700 ring-blue-200',  dot: true },
  E:         { cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  S:         { cls: 'bg-amber-50 text-amber-700 ring-amber-200' },
  mixed:     { cls: 'bg-orange-50 text-orange-700 ring-orange-200' },
}

const DOT: Record<string, string> = {
  ok:      'bg-emerald-500',
  error:   'bg-red-500',
  running: 'bg-blue-500 animate-pulse',
}

export default function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-slate-300">—</span>
  const config = MAP[value] ?? { cls: 'bg-slate-100 text-slate-600 ring-slate-200' }
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-medium ring-1 ring-inset ${config.cls}`}>
      {config.dot && DOT[value] && (
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${DOT[value]}`} />
      )}
      {value}
    </span>
  )
}
