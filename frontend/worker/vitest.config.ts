import { fileURLToPath } from 'node:url';

import { defineConfig } from 'vitest/config';

/**
 * Standalone Vitest config for the Cloudflare Worker script, deliberately
 * separate from Angular's own `ng test` (which is scoped to
 * `src/**\/*.spec.ts` via `tsconfig.spec.json` and runs through
 * `@angular/build:unit-test`, not a project-root `vitest.config.ts`).
 *
 * `root` is pinned to this file's own directory — Vitest's default root
 * for an explicit `--config` flag is the process cwd, not the config
 * file's location, which would otherwise also pick up (and fail to run,
 * since it depends on Angular's own test setup) `src/**\/*.spec.ts`.
 *
 * `environment: 'node'` is sufficient here: the Worker script under test
 * only uses the standard `Request`/`Response`/`Headers`/`fetch` globals
 * (all present in Node 18+), not Workers-runtime-specific bindings.
 */
export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  test: {
    include: ['**/*.spec.ts'],
    environment: 'node',
  },
});
