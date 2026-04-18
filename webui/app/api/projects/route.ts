import { NextResponse } from 'next/server'

const API = process.env.BIBLION_API_URL ?? 'http://localhost:18765'

interface ListEntry { id: string; type: string; project_id: string }
interface IndexerProject { project_id: string; chunk_count: number; file_count: number }

export async function GET() {
  try {
    const [listRes, idxRes] = await Promise.all([
      fetch(`${API}/biblion/list`, { cache: 'no-store' }),
      fetch(`${API}/indexer/projects`, { cache: 'no-store' }),
    ])

    const biblionEntries: ListEntry[] = listRes.ok ? await listRes.json() : []
    const indexerProjects: IndexerProject[] = idxRes.ok ? await idxRes.json() : []

    // Group biblion entries by project_id
    const biblionMap = new Map<string, { count: number; byType: Record<string, number> }>()
    for (const entry of biblionEntries) {
      const key = entry.project_id ?? ''
      if (!biblionMap.has(key)) biblionMap.set(key, { count: 0, byType: {} })
      const proj = biblionMap.get(key)!
      proj.count++
      proj.byType[entry.type] = (proj.byType[entry.type] ?? 0) + 1
    }

    const allIds = new Set([
      ...biblionMap.keys(),
      ...indexerProjects.map(p => p.project_id),
    ])

    const projects = Array.from(allIds).map(id => {
      const b = biblionMap.get(id) ?? { count: 0, byType: {} }
      const idx = indexerProjects.find(p => p.project_id === id) ?? { chunk_count: 0, file_count: 0 }
      return {
        projectId: id,
        biblionCount: b.count,
        biblionByType: b.byType,
        chunkCount: idx.chunk_count,
        fileCount: idx.file_count,
      }
    })

    return NextResponse.json(projects)
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}
