const BASE_URL = new URL('https://archimedes.market/');
const KNOWN_ASSET_ID = '7665aafa-08ff-4391-a1ef-82ea87ed4002';
const KNOWN_BOUNTY_ID = '5586f0c8-cde1-416c-ac28-d85bc6a264f0';
const USER_AGENT = 'archimedes-msn-00013-endpoint-probe/1.2 (+read-only; no-auth)';
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
  return [...urls].slice(0, 50);
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

function contextsForRegex(text, pattern, max = 20, radius = 260) {
  const output = [];
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    output.push({
      match: sanitize(match[0], 180),
      context: sanitize(text.slice(Math.max(0, index - radius), index + match[0].length + radius), 760),
    });
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

function jsonLdProducts(html) {
  const products = [];
  const normalized = normalizedSearchText(html);
  const pattern = /<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  for (const match of normalized.matchAll(pattern)) {
    const body = match[1];
    if (!body) {
      continue;
    }
    try {
      const value = JSON.parse(body);
      const candidates = Array.isArray(value) ? value : [value];
      for (const candidate of candidates) {
        if (candidate && typeof candidate === 'object' && candidate['@type'] === 'Product') {
          products.push(candidate);
        }
      }
    } catch {
      // React Flight also contains an escaped copy. Metadata below still proves the public product.
    }
  }
  return products;
}

function analyzeHtml(response) {
  const flight = decodeFlightPayload(response.body);
  const combined = normalizedSearchText(`${response.body}\n${flight.joined}`);
  const assetLinkIds = uniqueMatches(combined, new RegExp(`/assets/(${UUID_PATTERN})`, 'gi'), 1, 100);
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
    json_ld_products: jsonLdProducts(response.body),
    asset_link_count: assetLinkIds.length,
    asset_link_ids: assetLinkIds.slice(0, 30),
    uuid_count: allUuids.length,
    uuid_sample: allUuids.slice(0, 30),
    contains_known_asset_id: combined.toLowerCase().includes(KNOWN_ASSET_ID),
    targeted_evidence: [
      ...contextsForRegex(combined, new RegExp(KNOWN_ASSET_ID, 'gi'), 4),
      ...contextsForRegex(combined, /application\/ld\+json|"@type":"Product"|priceCurrency|additionalProperty/gi, 8),
    ],
  };
}

function scriptAnalysis(source, text) {
  const normalized = normalizedSearchText(text);
  const tableNames = uniqueMatches(
    normalized,
    /\.from\(["']([^"']*(?:asset|product|listing|catalog)[^"']*)["']\)/gi,
    1,
    30,
  );
  const rpcNames = uniqueMatches(normalized, /\.rpc\(["']([^"']+)["']/gi, 1, 30);
  const supabaseUrls = uniqueMatches(normalized, /https:\/\/[a-z0-9-]+\.supabase\.co/gi, 0, 10);
  const evidence = [
    ...contextsForRegex(normalized, /\.from\(["'][^"']*(?:asset|product|listing|catalog)[^"']*["']\)/gi, 20),
    ...contextsForRegex(normalized, /asset_type|price_cents|gallery_images|published_at|trust_score|license_type/gi, 20),
    ...contextsForRegex(normalized, /\.rpc\(["'][^"']+["']/gi, 10),
  ];
  return {
    source,
    bytes: Buffer.byteLength(text),
    table_names: tableNames,
    rpc_names: rpcNames,
    supabase_urls: supabaseUrls,
    evidence: evidence.slice(0, 40),
  };
}

function sitemapAnalysis(response) {
  const normalized = decodeHtmlEntities(response.body);
  const locations = uniqueMatches(normalized, /<loc>([^<]+)<\/loc>/gi, 1, 5_000);
  const assetLocations = locations.filter((value) => new RegExp(`/assets/${UUID_PATTERN}(?:$|[?#])`, 'i').test(value));
  return {
    url: response.url,
    status: response.status,
    content_type: response.content_type,
    location: response.location,
    error: response.error ?? null,
    bytes: Buffer.byteLength(response.body),
    body_prefix: sanitize(response.body, 1_200),
    location_count: locations.length,
    location_sample: locations.slice(0, 20),
    asset_location_count: assetLocations.length,
    asset_location_sample: assetLocations.slice(0, 30),
  };
}

const listingHtml = await fetchText('/assets', 'text/html,application/xhtml+xml');
const detailHtml = await fetchText(`/assets/${KNOWN_ASSET_ID}`, 'text/html,application/xhtml+xml');
const pages = [analyzeHtml(listingHtml), analyzeHtml(detailHtml)];

const scripts = new Set([...scriptUrls(listingHtml.body), ...scriptUrls(detailHtml.body)]);
const analyzedScripts = [];
for (const scriptUrl of [...scripts]) {
  const response = await fetchText(scriptUrl, 'application/javascript,text/javascript,*/*');
  if (response.status === 200 && response.body) {
    const analysis = scriptAnalysis(scriptUrl, response.body);
    if (
      analysis.table_names.length > 0 ||
      analysis.rpc_names.length > 0 ||
      analysis.supabase_urls.length > 0 ||
      analysis.evidence.length > 0
    ) {
      analyzedScripts.push(analysis);
    }
  }
}

const sitemapPaths = [
  '/robots.txt',
  '/sitemap.xml',
  '/sitemap_index.xml',
  '/sitemap-0.xml',
  '/assets-sitemap.xml',
  '/sitemaps/assets.xml',
];
const sitemaps = [];
for (const path of sitemapPaths) {
  sitemaps.push(sitemapAnalysis(await fetchText(path, 'application/xml,text/xml,text/plain,*/*')));
}

const candidatePaths = [
  '/api/public/assets?limit=1&offset=0',
  `/api/public/assets/${KNOWN_ASSET_ID}`,
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
      discovered_script_count: scripts.size,
      relevant_scripts: analyzedScripts,
      sitemaps,
      probes,
    },
    null,
    2,
  ),
);
