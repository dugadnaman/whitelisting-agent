import { NextRequest, NextResponse } from 'next/server';

async function handle(req: NextRequest, { params }: { params: { path: string[] } }) {
  const path = params.path.join('/');
  const searchParams = req.nextUrl.searchParams.toString();
  const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const url = `${backendUrl}/api/${path}${searchParams ? '?' + searchParams : ''}`;

  const headers = new Headers(req.headers);
  // Point Host to the internal backend service
  const host = backendUrl.replace(/^https?:\/\//, '');
  headers.set('host', host);

  try {
    // Forward the request body stream directly (duplex: 'half' required for Node fetch streaming)
    const res = await fetch(url, {
      method: req.method,
      headers: headers,
      body: req.method !== 'GET' && req.method !== 'HEAD' ? req.body : undefined,
      // @ts-ignore
      duplex: 'half',
    });

    return new NextResponse(res.body, {
      status: res.status,
      headers: res.headers,
    });
  } catch (err) {
    console.error(`Proxy error for ${url}:`, err);
    return NextResponse.json({ detail: String(err) }, { status: 502 });
  }
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const DELETE = handle;
