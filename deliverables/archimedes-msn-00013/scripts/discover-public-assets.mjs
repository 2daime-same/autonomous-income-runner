const BASE_URL = new URL('https://archimedes.market/');
const KNOWN_ASSET_ID = '7665aafa-08ff-4391-a1ef-82ea87ed4002';
const KNOWN_BOUNTY_ID = '5586f0c8-cde1-416c-ac28-d85bc6a264f0';
const USER_AGENT = 'archimedes-msn-00013-endpoint-probe/1.1 (+read-only; no-auth)';
const MAX_TEXT_BYTES = 2_000_000;
const UUID_PATTERN = '[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}';

function sanitize(text, limit = 700) {
  return String(text)
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, limit);
}

function decodeHtmlEntities(text) {
  return String(text)
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&amp;/gi, '&');
}

async function fetchText(pathOrUrl, accept = '*/*') {
  const url = new URL(pathOrUrl, BASE_URL);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  timer.unref?.();
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { accept, 'user-agent': USER_AGENT },
      redirect: 'manual',
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      signal: controller.signal,
    });
    const declared = Number(response.headers.get('content-length') ?? 0);
    if (Number.isFinite(declared) && declared > MAX_TEXT_BYTES) {
      await response.body?.cancel().catch(() => undefined);
      return {
        url: url.href,
        status: response.status,
        content_type: response.headers.get('content-type'),
        location: response.headers.get('location'),
        body: `[body omitted: declared ${declared} bytes]`,
      };
    }
    const body = await response.text();
    return {
      url: url.href,
      status: response.status,
      content_type: response.headers.get('content-type'),
      location: response.headers.get('location'),
      body: body.slice(0, MAX_TEXT_BYTES),
    };
  } catch (error) {
    return {
      url: url.href,
      status: null,
      content_type: null,
      location: null,
      body: '',
      error: error instanceof Error ? `${error.name}: ${error.message}` : 'unknown fetch error',
    };
  } finally {
    clearTimeout(timer);
  }
}

function scriptUrls(html) {
  const urls = new Set();
  for (const match of html.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["']/gi)) {
    const source = match[1];
    if (source) {
      urls.add(new URL(source, BASE_URL).href);
    }
  }
  return [...urls].slice(0, 40);
}

function decodeFlightPayload(html) {
  const segments = [];
  const pattern = /self\.__next_f\.push\(\[1,"((?:\\.|[^"\\])*)"\]\)/g;
  for (const match of html.matchAll(pattern)) {
    const encoded = match[1];
    if (!encoded) {
      continue;
    }
    try {
      segments.push(JSON.parse(`"${encoded}"`));
    } catch {
      segments.push(encoded);
    }
  }
  return { segments, joined: segments.join('\n') };
}

function normalizedSearchText(text) {
  return decodeHtmlEntities(String(text))
    .replace(/\\u002[fF]/g, '/')
    .replace(/\\\//g, '/')
    .replace(/\\"/g, '"');
}

function uniqueMatches(text, pattern, group = 0, max = 100) {
  const values = new Set();
  for (const match of text.matchAll(pattern)) {
    const value = match[group];
    if (value) {
      values.add(value);
    }
    if (values.size >= max) {
      break;
    }
  }
  return [...values];
}

function contexts(text, needles, max = 20, radius = 220) {
  const output = [];
  const lowered = text.toLowerCase();
  for (const needle of needles) {
    let cursor = 0;
    const normalizedNeedle = needle.toLowerCase();
    while (output.length < max) {
      const index = lowered.indexOf(normalizedNeedle, cursor);
      if (index < 0) {
        break;
      }
      output.push({
        needle,
        context: sanitize(text.slice(Math.max(0, index - radius), index + needle.length + radius), 600),
      });
      cursor = index + Math.max(needle.length, 1);
    }
    if (output.length >= max) {
      break;
    }
  }
  return output;
}

function metadata(html) {
  const output = {};
  const metaPattern = /<meta\b[^>]*(?:name|property)=["']([^"']+)["'][^>]*content=["']([^"']*)["'][^>]*>/gi;
  for (const match of html.matchAll(metaPattern)) {
    const key = match[1]?.toLowerCase();
    const value = match[2];
    if (key && value && ['title', 'description', 'og:title', 'og:description', 'og:url'].includes(key)) {
      output[key] = decodeHtmlEntities(value);
    }
  }
  const title = html.match(/<title>([^<]*)<\/title>/i)?.[1];
  if (title) {
    output.html_title = decodeHtmlEntities(title);
  }
  return output;
}

function analyzeHtml(response) {
  const flight = decodeFlightPayload(response.body);
  const combined = normalizedSearchText(`${response.body}\n${flight.joined}`);
  const assetLinkIds = uniqueMatches(
    combined,
    new RegExp(`/assets/(${UUID_PATTERN})`, 'gi'),
    1,
    100,
  );
  const allUuids = uniqueMatches(combined, new RegExp(UUID_PATTERN, 'gi'), 0, 200);
  return {
    url: response.url,
    status: response.status,
    content_type: response.content_type,
    location: response.location,
    error: response.error ?? null,
    html_bytes: Buffer.byteLength(response.body),
    flight_segment_count: flight.segments.length,
    flight_decoded_bytes: Buffer.byteLength(flight.joined),
    metadata: metadata(response.body),
    asset_link_count: assetLinkIds.length,
    asset_link_ids: assetLinkIds.slice(0, 30),
    uuid_count: allUuids.length,
    uuid_sample: allUuids.slice(0, 30),
    contains_known_asset_id: combined.toLowerCase().includes(KNOWN_ASSET_ID),
    contains_python: /python/i.test(combined),
    evidence: contexts(
      combined,
      [KNOWN_ASSET_ID, '/assets/', 'Python', 'asset_type', 'price_cents', 'seller', 'title'],
      24,
    ),
  };
}

function endpointEvidence(text, source) {
  const evidence = [];
  const normalized = normalizedSearchText(text);
  const lowered = normalized.toLowerCase();
  for (const needle of ['/api/', '/assets/', 'supabase', 'rpc(', 'from("assets', "from('assets"]) {
    let cursor = 0;
    while (evidence.length < 60) {
      const index = lowered.indexOf(needle.toLowerCase(), cursor);
      if (index < 0) {
        break;
      }
      const context = sanitize(normalized.slice(Math.max(0, index - 160), index + 420), 650);
      if (/asset|solution|bount|marketplace|catalog|supabase/i.test(context)) {
        evidence.push({ source, needle, context });
      }
      cursor = index + needle.length;
    }
  }
  return evidence;
}

const queryPages = [
  '/assets',
  '/assets?q=Python',
  '/assets?query=Python',
  '/assets?search=Python',
  '/assets?asset_type=CODE',
  `/assets/${KNOWN_ASSET_ID}`,
];
const pages = [];
for (const path of queryPages) {
  pages.push(analyzeHtml(await fetchText(path, 'text/html,application/xhtml+xml')));
}

const listingHtml = await fetchText('/assets', 'text/html,application/xhtml+xml');
const scripts = scriptUrls(listingHtml.body);
const evidence = [];
for (const scriptUrl of scripts) {
  const response = await fetchText(scriptUrl, 'application/javascript,text/javascript,*/*');
  if (response.status === 200 && response.body) {
    evidence.push(...endpointEvidence(response.body, scriptUrl));
  }
  if (evidence.length >= 60) {
    break;
  }
}

const candidatePaths = [
  '/api/public/assets?limit=1&offset=0',
  '/api/assets?limit=1&offset=0',
  '/api/marketplace/assets?limit=1&offset=0',
  '/api/public/marketplace/assets?limit=1&offset=0',
  '/api/public/solutions?limit=1&offset=0',
  '/api/solutions?limit=1&offset=0',
  '/api/catalog/assets?limit=1&offset=0',
  '/api/assets/search?limit=1&offset=0',
  `/api/public/assets/${KNOWN_ASSET_ID}`,
  `/api/assets/${KNOWN_ASSET_ID}`,
  `/api/marketplace/assets/${KNOWN_ASSET_ID}`,
  '/api/public/bounties?status=open&limit=1&offset=0',
  `/api/public/bounties/${KNOWN_BOUNTY_ID}`,
];

const probes = [];
for (const path of candidatePaths) {
  const response = await fetchText(path, 'application/json,text/plain,*/*');
  probes.push({
    path,
    status: response.status,
    content_type: response.content_type,
    location: response.location,
    body_prefix: sanitize(response.body),
    error: response.error ?? null,
  });
}

console.log(
  JSON.stringify(
    {
      generated_at: new Date().toISOString(),
      policy: 'Unauthenticated GET requests only; no account, terms, claim, purchase, upload, or payment action.',
      pages,
      discovered_script_count: scripts.length,
      script_endpoint_evidence: evidence.slice(0, 60),
      probes,
    },
    null,
    2,
  ),
);
