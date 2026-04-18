import { NextResponse } from 'next/server'

const API = process.env.BIBLION_API_URL ?? 'http://localhost:18765'

export async function GET() {
  try {
    const [biblionRes, indexerRes] = await Promise.all([
      fetch(`${API}/biblion/status`, { cache: 'no-store' }),
      fetch(`${API}/indexer/status`, { cache: 'no-store' }),
    ])
    const biblion = biblionRes.ok ? await biblionRes.json() : { type: 'disabled', reason: 'unreachable' }
    const indexer = indexerRes.ok ? await indexerRes.json() : { status: 'disabled', reason: 'unreachable' }
    return NextResponse.json({ biblion, indexer })
  } catch {
    return NextResponse.json({
      biblion: { type: 'disabled', reason: 'unreachable' },
      indexer: { status: 'disabled', reason: 'unreachable' },
    })
  }
}
