/**
 * Streams a call-recording audio file from the shared /data volume.
 * Security: only paths under DATA_DIR are allowed.
 */
import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

const DATA_DIR = path.normalize(process.env.DATA_DIR ?? '/data');

export async function GET(req: NextRequest) {
  const filePath = req.nextUrl.searchParams.get('path');
  if (!filePath) {
    return NextResponse.json({ error: 'Missing path parameter' }, { status: 400 });
  }

  // Security: reject any path that doesn't live inside DATA_DIR
  const normalized = path.normalize(filePath);
  if (!normalized.startsWith(DATA_DIR)) {
    return NextResponse.json({ error: 'Forbidden' }, { status: 403 });
  }

  try {
    if (!fs.existsSync(normalized)) {
      return NextResponse.json({ error: 'File not found' }, { status: 404 });
    }

    const stat = fs.statSync(normalized);
    const ext  = path.extname(normalized).toLowerCase();
    const mime =
      ext === '.mp3' ? 'audio/mpeg' :
      ext === '.ogg' ? 'audio/ogg'  :
      ext === '.wav' ? 'audio/wav'  : 'audio/octet-stream';

    // Support partial content (Range requests) so the audio tag can seek
    const range = req.headers.get('range');
    if (range) {
      const [startStr, endStr] = range.replace(/bytes=/, '').split('-');
      const start = parseInt(startStr, 10);
      const end   = endStr ? parseInt(endStr, 10) : stat.size - 1;
      const chunk = end - start + 1;

      const stream = fs.createReadStream(normalized, { start, end });
      return new NextResponse(stream as unknown as ReadableStream, {
        status: 206,
        headers: {
          'Content-Type': mime,
          'Content-Range': `bytes ${start}-${end}/${stat.size}`,
          'Accept-Ranges': 'bytes',
          'Content-Length': String(chunk),
        },
      });
    }

    const buffer = fs.readFileSync(normalized);
    return new NextResponse(buffer, {
      status: 200,
      headers: {
        'Content-Type': mime,
        'Content-Length': String(stat.size),
        'Accept-Ranges': 'bytes',
      },
    });
  } catch {
    return NextResponse.json({ error: 'Could not read file' }, { status: 500 });
  }
}
