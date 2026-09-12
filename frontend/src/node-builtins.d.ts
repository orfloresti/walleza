/**
 * Minimal ambient typings for the Node.js builtin used by `styles.spec.ts`.
 *
 * The workspace has no `@types/node` devDependency (design keeps the phase
 * dependency-free); Vitest's Node runtime resolves this module fine at test
 * time, but the Angular compiler's type-check step needs a declaration to
 * accept the import. Scoped to only the export actually used.
 */

declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf-8'): string;
}
