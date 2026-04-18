import { NextResponse } from 'next/server'

const API = process.env.BIBLION_API_URL ?? 'http://localhost:18765'

export async function DELETE(request: Request) {
  const { searchParams } = new URL(request.url)
  const projectId = searchParams.get('project_id')

  const url = new URL(`${API}/biblion/clear`)
  if (projectId !== null) url.searchParams.set('project_id', projectId)

  try {
    const res = await fetch(url.toString(), { method: 'DELETE' })
    if (res.headers.get('content-type')?.includes('application/json')) {
      const data = await res.json()
      return NextResponse.json(data, { status: res.status })
    }
    return NextResponse.json({ error: 'Upstream returned non-JSON response' }, { status: res.status })
  } catch {
    return NextResponse.json({ error: 'Upstream API is unreachable' }, { status: 503 })
  }
}
