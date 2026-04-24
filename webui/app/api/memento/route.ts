import { NextRequest, NextResponse } from 'next/server'

const API = process.env.BIBLION_API_URL ?? 'http://localhost:18765'

export async function GET(req: NextRequest) {
  const project_id = req.nextUrl.searchParams.get('project_id') ?? ''
  try {
    const res = await fetch(`${API}/biblion/memento/list?project_id=${encodeURIComponent(project_id)}`, { cache: 'no-store' })
    if (!res.ok) return NextResponse.json([], { status: res.status })
    return NextResponse.json(await res.json())
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const res = await fetch(`${API}/biblion/memento/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return NextResponse.json(await res.json(), { status: res.status })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}

export async function DELETE(req: NextRequest) {
  const project_id = req.nextUrl.searchParams.get('project_id')
  if (!project_id) return NextResponse.json({ error: 'project_id required' }, { status: 400 })
  try {
    const res = await fetch(`${API}/biblion/memento/clear?project_id=${encodeURIComponent(project_id)}`, { method: 'DELETE' })
    return NextResponse.json(await res.json(), { status: res.status })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}
