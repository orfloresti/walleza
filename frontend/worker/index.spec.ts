/**
 * RED -> GREEN: a request to `/api/*` must never be served the SPA's
 * `index.html` (task 3.8, design D9).
 *
 * `wrangler.toml`'s static-assets binding is configured with
 * `not_found_handling: single-page-application`, which means ANY
 * unmatched path falls back to `index.html`. Without an explicit
 * `/api/*` branch in the Worker script, checked BEFORE the assets
 * fallback, a request to an unimplemented or typo'd API route would
 * silently return the SPA shell instead of a real response/error from
 * the backend — this test exercises the actual routing decision, not
 * just a string assertion.
 *
 * Uses plain Vitest with a mocked `env.ASSETS.fetch` and a mocked
 * global `fetch` (the API proxy target) rather than
 * `@cloudflare/vitest-pool-workers`: the Worker script here has no
 * Workers-runtime-specific API surface (no KV/Durable Objects/etc.),
 * only the standard `Request`/`Response`/`fetch` primitives Node
 * already provides, so the heavier Workers-pool tooling would add
 * setup cost without exercising anything the standard runtime can't.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import worker, { type Env } from './index';

const SPA_SHELL_BODY = '<!doctype html><html><body>SPA shell</body></html>';

function makeEnv(): Env {
  return {
    API_ORIGIN: 'https://api.internal.example.com',
    WORKER_ORIGIN_TOKEN: 'test-origin-token',
    ASSETS: {
      fetch: vi.fn(
        async () =>
          new Response(SPA_SHELL_BODY, {
            status: 200,
            headers: { 'content-type': 'text/html' },
          }),
      ),
    },
  };
}

describe('Worker routing', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('does not serve the SPA shell for an /api/* request', async () => {
    const env = makeEnv();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const request = new Request('https://walleza.orfloresti.dev/api/health');
    const response = await worker.fetch(request, env);
    const body = await response.text();

    expect(body).not.toContain('SPA shell');
    expect(env.ASSETS.fetch).not.toHaveBeenCalled();
  });

  it('proxies /api/* to API_ORIGIN, not to the assets binding', async () => {
    const env = makeEnv();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 200 }));

    const request = new Request('https://walleza.orfloresti.dev/api/me');
    await worker.fetch(request, env);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const forwardedRequest = fetchSpy.mock.calls[0][0] as Request;
    expect(forwardedRequest.url).toBe('https://api.internal.example.com/api/me');
    expect(env.ASSETS.fetch).not.toHaveBeenCalled();
  });

  it('injects the X-Origin-Token header on the proxied request', async () => {
    const env = makeEnv();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 200 }));

    const request = new Request('https://walleza.orfloresti.dev/api/auth/refresh', {
      method: 'POST',
    });
    await worker.fetch(request, env);

    const forwardedRequest = fetchSpy.mock.calls[0][0] as Request;
    expect(forwardedRequest.headers.get('X-Origin-Token')).toBe('test-origin-token');
    expect(forwardedRequest.method).toBe('POST');
  });

  it('preserves the query string when proxying /api/*', async () => {
    const env = makeEnv();
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response('{}', { status: 200 }));

    const request = new Request(
      'https://walleza.orfloresti.dev/api/auth/callback?code=abc&state=xyz',
    );
    await worker.fetch(request, env);

    const forwardedRequest = fetchSpy.mock.calls[0][0] as Request;
    expect(forwardedRequest.url).toBe(
      'https://api.internal.example.com/api/auth/callback?code=abc&state=xyz',
    );
  });

  it('serves the SPA shell (via the assets binding) for a non-API navigation route', async () => {
    const env = makeEnv();
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    const request = new Request('https://walleza.orfloresti.dev/dashboard');
    const response = await worker.fetch(request, env);
    const body = await response.text();

    expect(body).toContain('SPA shell');
    expect(env.ASSETS.fetch).toHaveBeenCalledTimes(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('Cache-Control headers (task 6.6, design D6a)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it.each(['/', '/index.html', '/ngsw.json'])(
    'forces no-cache on %s so a deploy is always visible on the next request',
    async (path) => {
      const env = makeEnv();

      const response = await worker.fetch(
        new Request(`https://walleza.orfloresti.dev${path}`),
        env,
      );

      expect(response.headers.get('Cache-Control')).toBe('no-cache');
    },
  );

  it('sets an immutable long TTL on content-hashed JS/CSS bundles', async () => {
    const env = makeEnv();

    const jsResponse = await worker.fetch(
      new Request('https://walleza.orfloresti.dev/main-S2RZWZQN.js'),
      env,
    );
    const cssResponse = await worker.fetch(
      new Request('https://walleza.orfloresti.dev/styles-5QHGVCTR.css'),
      env,
    );

    expect(jsResponse.headers.get('Cache-Control')).toBe(
      'public, max-age=31536000, immutable',
    );
    expect(cssResponse.headers.get('Cache-Control')).toBe(
      'public, max-age=31536000, immutable',
    );
  });

  it('leaves the assets-binding Cache-Control untouched for non-hashed, non-shell paths', async () => {
    const env = makeEnv();

    const response = await worker.fetch(
      new Request('https://walleza.orfloresti.dev/manifest.webmanifest'),
      env,
    );

    expect(response.headers.get('Cache-Control')).toBeNull();
  });

  it('does not rewrite Cache-Control on /api/* responses', async () => {
    const env = makeEnv();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Cache-Control': 'private' } }),
    );

    const response = await worker.fetch(
      new Request('https://walleza.orfloresti.dev/api/me'),
      env,
    );

    expect(response.headers.get('Cache-Control')).toBe('private');
  });
});
