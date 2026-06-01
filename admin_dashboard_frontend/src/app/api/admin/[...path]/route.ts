/**
 * Catch-all proxy to logic_service /admin/*.
 *
 * Streams request and response bodies (so multipart uploads and binary/CSV
 * downloads work), while forwarding the Authorization header.
 *
 * LOGIC_SERVICE_URL defaults work for both Docker (http://logic_service:8000)
 * and local dev (http://localhost:8002).
 */
import { NextRequest, NextResponse } from 'next/server';

const LOGIC_SERVICE_URL =
  process.env.LOGIC_SERVICE_URL ?? 'http://localhost:8002';

type Props = { params: Promise<{ path: string[] }> };

const COPY_REQUEST_HEADERS = ['authorization', 'content-type', 'accept', 'range'];
const STRIP_RESPONSE_HEADERS = new Set([
  'transfer-encoding',
  'content-encoding',
  'connection',
]);

async function proxyHandler(req: NextRequest, props: Props) {
  const { path } = await props.params;
  const urlPath = path.join('/');
  const targetUrl = `${LOGIC_SERVICE_URL}/admin/${urlPath}${req.nextUrl.search}`;

  const headers: Record<string, string> = {};
  for (const name of COPY_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers[name] = value;
  }
  const queryToken = req.nextUrl.searchParams.get('token');
  if (queryToken && !headers.authorization) {
    headers.authorization = `Bearer ${queryToken}`;
  }

  const init: RequestInit = { method: req.method, headers, redirect: 'manual' };

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    const buffer = await req.arrayBuffer();
    if (buffer.byteLength > 0) {
      init.body = buffer;
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl, init);
  } catch {
    return NextResponse.json(
      { detail: 'Backend service unreachable' },
      { status: 503 },
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIP_RESPONSE_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value);
    }
  });

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET    = proxyHandler;
export const POST   = proxyHandler;
export const PUT    = proxyHandler;
export const DELETE = proxyHandler;
