/**
 * Parity spec for `styles.css`, design D62.
 *
 * Token values are declared exactly once as `--wz-{light,dark}-*` sources
 * inside `:root`, then mapped by `var()` into the four cascade blocks
 * (`:root`, the dark `prefers-color-scheme` media query's nested `:root`,
 * and the two inert `[data-theme]` mirrors). Four near-identical literal
 * blocks invite a specific silent failure: a token edited or added in three
 * blocks but missed in the fourth reviews as clean and drifts unnoticed —
 * and because the `[data-theme]` blocks are inert until a future manual
 * toggle ships, that drift stays invisible until the worst possible moment.
 *
 * This spec guards two things structurally, not by convention:
 * 1. All four cascade blocks declare an identical token-name set.
 * 2. Every `--wz-*` source is referenced somewhere via `var()` (catches an
 *    orphaned source left behind by a later edit).
 * 3. No `oklch()` literal escapes the `:root` source region — the four
 *    mapping blocks must contain only `var()` remappings plus
 *    `color-scheme`, never a literal color.
 */

import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

/**
 * Relative to the Angular workspace root (`frontend/`), which is the
 * process cwd `ng test` runs under. `import.meta.url` is deliberately not
 * used here: combined with a `node:fs`/`node:url` import, this workspace's
 * unit-test builder resolves it to a synthetic `http://localhost` URL
 * instead of a real `file:` one, which makes `fileURLToPath` throw.
 */
const CSS_PATH = 'src/styles.css';

interface CssBlock {
  readonly selector: string;
  readonly body: string;
}

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '');
}

/**
 * Splits CSS text into its top-level blocks (selector + brace-matched body).
 * A top-level `;` (e.g. `@import "tailwindcss";`) ends a bodyless statement
 * and resets selector tracking, so it is never absorbed into the next
 * block's selector text.
 */
function splitTopLevelBlocks(css: string): CssBlock[] {
  const blocks: CssBlock[] = [];
  let selectorStart = 0;
  let i = 0;
  while (i < css.length) {
    if (css[i] === ';') {
      selectorStart = i + 1;
      i++;
      continue;
    }
    if (css[i] === '{') {
      const selector = css.slice(selectorStart, i).trim();
      let depth = 1;
      let j = i + 1;
      while (j < css.length && depth > 0) {
        if (css[j] === '{') depth++;
        else if (css[j] === '}') depth--;
        j++;
      }
      const body = css.slice(i + 1, j - 1);
      blocks.push({ selector, body });
      i = j;
      selectorStart = i;
      continue;
    }
    i++;
  }
  return blocks;
}

/**
 * Custom-property names (without the leading `--`) declared directly inside
 * `body`, excluding `--wz-*` sources — those are the raw value catalog, not
 * the live token set a cascade block is expected to remap.
 */
function declaredTokenNames(body: string): Set<string> {
  const names = new Set<string>();
  const re = /--([a-z0-9-]+)\s*:/gi;
  let match: RegExpExecArray | null;
  while ((match = re.exec(body))) {
    const name = match[1];
    if (!name.startsWith('wz-')) {
      names.add(name);
    }
  }
  return names;
}

function sortedArray(set: Set<string>): string[] {
  return [...set].sort();
}

const rawCss = readFileSync(CSS_PATH, 'utf-8');
const css = stripComments(rawCss);
const topLevelBlocks = splitTopLevelBlocks(css);

const rootBlock = topLevelBlocks.find((b) => b.selector === ':root');
const darkMediaBlock = topLevelBlocks.find((b) =>
  b.selector.replace(/\s+/g, ' ').startsWith('@media (prefers-color-scheme: dark)'),
);
const dataThemeDarkBlock = topLevelBlocks.find((b) => b.selector === '[data-theme="dark"]');
const dataThemeLightBlock = topLevelBlocks.find((b) => b.selector === '[data-theme="light"]');

describe('styles.css — D62 token cascade parity', () => {
  it('declares all four cascade blocks', () => {
    expect(rootBlock, ':root block').toBeDefined();
    expect(darkMediaBlock, '@media (prefers-color-scheme: dark) block').toBeDefined();
    expect(dataThemeDarkBlock, '[data-theme="dark"] block').toBeDefined();
    expect(dataThemeLightBlock, '[data-theme="light"] block').toBeDefined();
  });

  it('declares an identical token-name set across all four cascade blocks', () => {
    const nestedRootBlock = splitTopLevelBlocks(darkMediaBlock?.body ?? '').find(
      (b) => b.selector === ':root',
    );
    expect(nestedRootBlock, 'nested :root inside the dark media query').toBeDefined();

    const rootTokens = sortedArray(declaredTokenNames(rootBlock?.body ?? ''));
    const darkMediaTokens = sortedArray(declaredTokenNames(nestedRootBlock?.body ?? ''));
    const dataThemeDarkTokens = sortedArray(declaredTokenNames(dataThemeDarkBlock?.body ?? ''));
    const dataThemeLightTokens = sortedArray(declaredTokenNames(dataThemeLightBlock?.body ?? ''));

    expect(rootTokens.length).toBeGreaterThan(0);
    expect(darkMediaTokens).toEqual(rootTokens);
    expect(dataThemeDarkTokens).toEqual(rootTokens);
    expect(dataThemeLightTokens).toEqual(rootTokens);
  });

  it('includes the success and warning semantic token pairs in every block', () => {
    const rootTokens = declaredTokenNames(rootBlock?.body ?? '');
    for (const name of ['success', 'on-success', 'warning', 'on-warning']) {
      expect(rootTokens.has(name), `--${name} declared in :root`).toBe(true);
    }
  });

  it('references every declared --wz-* source at least once via var()', () => {
    const wzDeclarationRe = /--(wz-(?:light|dark)-[a-z-]+)\s*:/gi;
    const declared = new Set<string>();
    let match: RegExpExecArray | null;
    while ((match = wzDeclarationRe.exec(css))) {
      declared.add(match[1]);
    }

    expect(declared.size).toBeGreaterThan(0);

    for (const name of declared) {
      const referenceRe = new RegExp(`var\\(--${name}\\)`);
      expect(referenceRe.test(css), `var(--${name}) is referenced somewhere in styles.css`).toBe(
        true,
      );
    }
  });

  it('confines every oklch() literal to the :root source region', () => {
    const rootStart = css.indexOf(':root');
    expect(rootStart, ':root selector found').toBeGreaterThanOrEqual(0);

    const rootBraceStart = css.indexOf('{', rootStart);
    let depth = 1;
    let i = rootBraceStart + 1;
    while (i < css.length && depth > 0) {
      if (css[i] === '{') depth++;
      else if (css[i] === '}') depth--;
      i++;
    }
    const rootBraceEnd = i;

    const outsideRoot = css.slice(0, rootStart) + css.slice(rootBraceEnd);
    expect(outsideRoot.includes('oklch(')).toBe(false);
  });
});
