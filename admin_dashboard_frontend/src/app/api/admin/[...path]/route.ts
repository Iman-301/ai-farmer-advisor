/**
 * Catch-all proxy to the logic_service /admin/* endpoints.
 * The frontend container never exposes the backend URL to the browser:
 * all calls go through this server-side route.
 *
 * LOGIC_SERVICE_URL defaults work for both Docker (http://logic_service:8000)
 * and local dev (http://localhost:8002).
 */
import { NextRequest, NextResponse } from 'next/server';

const LOGIC_SERVICE_URL =
  process.env.LOGIC_SERVICE_URL ?? 'http://localhost:8002';

type Props = { params: Promise<{ path: string[] }> };

async function proxyHandler(req: NextRequest, props: Props) {
  const { path } = await props.params;
  const urlPath = path.join('/');
  const targetUrl = `${LOGIC_SERVICE_URL}/admin/${urlPath}${req.nextUrl.search}`;

  // Forward the Authorization header from the browser
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const auth = req.headers.get('authorization');
  if (auth) headers['Authorization'] = auth;

  // Forward the request body for non-GET methods
  let body: string | undefined;
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    body = await req.text();
  }

  try {
    const upstream = await fetch(targetUrl, {
      method: req.method,
      headers,
      body,
    });
    const json = await upstream.json().catch(() => null);
    return NextResponse.json(json ?? {}, { status: upstream.status });
  } catch {
    return NextResponse.json(
      { detail: 'Backend service unreachable' },
      { status: 503 },
    );
  }
}

export const GET    = proxyHandler;
export const POST   = proxyHandler;
export const PUT    = proxyHandler;
export const DELETE = proxyHandler;
