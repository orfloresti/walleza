# Frontend

This project was generated using [Angular CLI](https://github.com/angular/angular-cli) version 22.1.7.

## Prerequisites

- Node.js `24.20.0` or newer (pinned in `.nvmrc`; Angular 22 requires
  Node `^22.22.3 || ^24.15.0 || >=26.0.0` — a plain `24.11.0` install is
  **not** enough). Use [fnm](https://github.com/Schniz/fnm) or
  [nvm](https://github.com/nvm-sh/nvm): `fnm use` (reads `.nvmrc`) or
  `nvm use`.
- npm `11.x` (ships with the Node version above).
- No global Angular CLI install is required — all scripts below run the
  workspace's local `@angular/cli` via `npm run` / `npx ng`.

## Scripts

| Command | Purpose |
|---|---|
| `npm run lint` | ESLint via `@angular-eslint` |
| `npm run build` | Production build (`dist/frontend`) |
| `npm test` | Angular app unit tests via Vitest (`@angular/build:unit-test`, `src/**/*.spec.ts`) |
| `npm run test:worker` | Cloudflare Worker unit tests via plain Vitest (`worker/**/*.spec.ts`) |
| `npm start` | Local dev server (`ng serve`) |

## Cloudflare Worker (`worker/`, `wrangler.toml`)

`worker/index.ts` is the single Cloudflare Worker that fronts this app in
production (design D9): it serves the `ng build` static output via the
Workers static-assets binding AND proxies `/api/*` requests to the
backend Lambda Function URL, injecting the `X-Origin-Token` header the
backend's origin-token middleware (`backend/app/main.py`) requires.
Same-origin removes CORS entirely and keeps cookie-based auth viable.

It is intentionally NOT part of the Angular app build (`ng build`/`ng
test`/`ng lint` never touch `worker/`) — it is a separate small script
with its own Vitest config (`worker/vitest.config.ts`), run via `npm run
test:worker`.

`wrangler.toml` defines two named environments, `staging` and
`production` (PR5, task 7.2/7.3), each with its own `API_ORIGIN` var and a
`WORKER_ORIGIN_TOKEN` secret set independently per environment:

```bash
wrangler secret put WORKER_ORIGIN_TOKEN --env staging
wrangler secret put WORKER_ORIGIN_TOKEN --env production
```

`API_ORIGIN` in both environments is still a placeholder Lambda Function
URL — no real Cloudflare account, zone, or Lambda deployment exists in
this sandbox. `.github/workflows/ci-cd.yml`'s deploy job runs
`npx wrangler deploy --env <staging|production>` for real once those
exist (production's DNS cutover to `walleza.orfloresti.dev` is PR6 scope).
`npx wrangler deploy --env staging --dry-run` and
`npx wrangler deploy --env production --dry-run` were both run during PR5
against the real `wrangler` CLI (no Cloudflare account needed for a dry
run) and both pass — see `sdd/phase-0-platform-foundation/apply-progress`
for the exact output. See `wrangler.toml`'s own comments and
`backend/README.md`'s "Authentication" section for the backend half of
this wiring.

## Development server

To start a local development server, run:

```bash
ng serve
```

Once the server is running, open your browser and navigate to `http://localhost:4200/`. The application will automatically reload whenever you modify any of the source files.

## Code scaffolding

Angular CLI includes powerful code scaffolding tools. To generate a new component, run:

```bash
ng generate component component-name
```

For a complete list of available schematics (such as `components`, `directives`, or `pipes`), run:

```bash
ng generate --help
```

## Building

To build the project run:

```bash
ng build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Vitest](https://vitest.dev/) test runner, use the following command:

```bash
ng test
```

## Running end-to-end tests

For end-to-end (e2e) testing, run:

```bash
ng e2e
```

Angular CLI does not come with an end-to-end testing framework by default. You can choose one that suits your needs.

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
