// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function exportCSV(data: any[], filename: string) {
  if (!data.length) return
  const rows = data as Row[]
  const headers = Object.keys(rows[0])
  const lines = rows.map((r) =>
    headers.map((h) => {
      const v = r[h]
      const s = v == null ? '' : String(v)
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? `"${s.replace(/"/g, '""')}"` : s
    }).join(',')
  )
  const csv = [headers.join(','), ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
