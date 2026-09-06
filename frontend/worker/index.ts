/**
 * Cloudflare Worker: serves the Angular SPA's static build and proxies
 * `/api/*` to the backend Lambda Function URL, injecting the
 * `X-Origin-Token` header FastAPI's origin-token middleware requires
 * (design D9). Same-origin for both app and API removes CORS entirely
 * and keeps cookie-based auth viable (`SameSite=Lax`).
 *
 * `/api/*` MUST be checked and proxied BEFORE the static-assets fallback
 * (task 3.8 / `index.spec.ts`). `wrangler.toml`'s asset binding is
 * configured with `not_found_handling: single-page-application`, which
 * means any unmatched path falls back to `index.html` — without this
 * explicit branch, a typo'd or unimplemented API route would silently
 * return the SPA shell instead of a real response/error from the
 * backend.
 *
 * Every non-API response also gets its `Cache-Control` header corrected
 * (task 6.6 / design D6a): `index.html` and `ngsw.json` MUST be
 * revalidated on every request or Cloudflare's edge pins a stale shell
 * and no tab ever learns a new version was deployed, while the
 * content-hashed JS/CSS bundles `ng build` emits are safe to cache
 * immutably for a long TTL, since a new deploy always produces a new
 * URL for them.
 */

/** Cloudflare Workers static-assets binding (`wrangler.toml` `[assets]`). */
interface AssetsBinding {
  fetch(request: Request): Promise<Response>;
}

export interface Env {
  ASSETS: AssetsBinding;
  /** Base URL of the Lambda Function URL the API is proxied to. */
  API_ORIGIN: string;
  /**
   * Shared secret injected as `X-Origin-Token` on every proxied request;
   * verified by FastAPI's origin-token middleware (design D9) so the
   * Function URL — public, `AuthType: NONE` — only ever accepts traffic
   * that passed through this Worker.
   */
  WORKER_ORIGIN_TOKEN: string;
}

const API_PREFIX = '/api/';

/** Content-hashed esbuild output, e.g. `main-S2RZWZQN.js`, `styles-5QHGVCTR.css`. */
const HASHED_ASSET_PATTERN = /-[A-Z0-9]{6,}\.(js|css)$/i;

/** Paths that MUST be revalidated on every request (design D6a). */
const NEVER_CACHE_PATHS = new Set(['/', '/index.html', '/ngsw.json']);

const worker = {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname.startsWith(API_PREFIX)) {
      return proxyToApi(request, url, env);
    }

    const assetResponse = await env.ASSETS.fetch(request);
    return withCacheHeaders(assetResponse, url.pathname);
  },
};

export default worker;

function withCacheHeaders(response: Response, pathname: string): Response {
  let cacheControl: string | null = null;

  if (NEVER_CACHE_PATHS.has(pathname)) {
    cacheControl = 'no-cache';
  } else if (HASHED_ASSET_PATTERN.test(pathname)) {
    cacheControl = 'public, max-age=31536000, immutable';
  }

  if (cacheControl === null) {
    return response;
  }

  const headers = new Headers(response.headers);
  headers.set('Cache-Control', cacheControl);

  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

async function proxyToApi(request: Request, url: URL, env: Env): Promise<Response> {
  const upstreamUrl = new URL(url.pathname + url.search, env.API_ORIGIN);

  const upstreamHeaders = new Headers(request.headers);
  upstreamHeaders.set('X-Origin-Token', env.WORKER_ORIGIN_TOKEN);

  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
  // Buffered rather than streamed: `/api/*` traffic here is auth/API
  // JSON payloads, never large uploads, and buffering avoids the
  // `duplex: 'half'` requirement (and cross-runtime inconsistencies)
  // that come with forwarding a live request body stream.
  const body = hasBody ? await request.arrayBuffer() : undefined;

  const upstreamRequest = new Request(upstreamUrl.toString(), {
    method: request.method,
    headers: upstreamHeaders,
    body,
    redirect: 'manual',
  });

  return fetch(upstreamRequest);
}
