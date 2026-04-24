import { NextRequest, NextResponse } from 'next/server'

const API = process.env.BIBLION_API_URL ?? 'http://localhost:18765'

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  try {
    const res = await fetch(`${API}/biblion/${id}`, { method: 'DELETE' })
    return NextResponse.json(await res.json(), { status: res.status })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}
