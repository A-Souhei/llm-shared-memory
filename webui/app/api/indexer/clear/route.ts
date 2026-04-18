import { NextResponse } from 'next/server'

const API = process.env.BIBLION_API_URL ?? 'http://localhost:18765'

export async function DELETE(request: Request) {
  try {
    const body = await request.json()
    const res = await fetch(`${API}/indexer/clear`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: body.project_id }),
    })
    if (res.headers.get('content-type')?.includes('application/json')) {
      const data = await res.json()
      return NextResponse.json(data, { status: res.status })
    }
    return NextResponse.json({ error: 'Upstream returned non-JSON response' }, { status: res.status })
  } catch {
    return NextResponse.json({ error: 'Upstream API is unreachable' }, { status: 503 })
  }
}
