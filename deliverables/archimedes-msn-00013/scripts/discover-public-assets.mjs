const BASE_URL = new URL('https://archimedes.market/');
const KNOWN_ASSET_ID = '7665aafa-08ff-4391-a1ef-82ea87ed4002';
const KNOWN_BOUNTY_ID = '5586f0c8-cde1-416c-ac28-d85bc6a264f0';
const USER_AGENT = 'archimedes-msn-00013-endpoint-probe/1.0 (+read-only; no-auth)';
const MAX_TEXT_BYTES = 2_000_000;

function sanitize(text, limit = 700) {
  return String(text)
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, limit);
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
  return [...urls].slice(0, 30);
}

function endpointEvidence(text, source) {
  const evidence = [];
  const lowered = text.toLowerCase();
  let cursor = 0;
  while (evidence.length < 50) {
    const index = lowered.indexOf('/api/', cursor);
    if (index < 0) {
      break;
    }
    const context = sanitize(text.slice(Math.max(0, index - 120), index + 320), 500);
    if (/asset|solution|bount|marketplace|catalog/i.test(context)) {
      evidence.push({ source, context });
    }
    cursor = index + 5;
  }
  return evidence;
}

const pages = [];
for (const path of ['/assets', `/assets/${KNOWN_ASSET_ID}`]) {
  const response = await fetchText(path, 'text/html,application/xhtml+xml');
  pages.push({
    url: response.url,
    status: response.status,
    content_type: response.content_type,
    location: response.location,
    body_prefix: sanitize(response.body),
    error: response.error ?? null,
  });
}

const listingHtml = await fetchText('/assets', 'text/html,application/xhtml+xml');
const scripts = scriptUrls(listingHtml.body);
const evidence = [];
for (const scriptUrl of scripts) {
  const response = await fetchText(scriptUrl, 'application/javascript,text/javascript,*/*');
  if (response.status === 200 && response.body) {
    evidence.push(...endpointEvidence(response.body, scriptUrl));
  }
  if (evidence.length >= 50) {
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
      endpoint_evidence: evidence.slice(0, 50),
      probes,
    },
    null,
    2,
  ),
);
