type Row = Record<string, unknown>

export function exportCSV(data: Row[], filename: string) {
  if (!data.length) return
  const headers = Object.keys(data[0])
  const rows = data.map((r) =>
    headers.map((h) => {
      const v = r[h]
      const s = v == null ? '' : String(v)
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? `"${s.replace(/"/g, '""')}"` : s
    }).join(',')
  )
  const csv = [headers.join(','), ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
