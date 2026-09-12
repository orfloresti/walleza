/**
 * `shared/ui/` public surface (design D63). Barrel-exported so feature
 * pages import via a relative path (`'../../../shared/ui'`), matching
 * this repo's existing convention of relative cross-feature imports.
 * Standalone components are ordinary classes referenced from a
 * component's own `imports: []`, so esbuild tree-shakes any entry a
 * chunk never uses.
 */
export * from './button/ui-button.component';
export * from './field/ui-field.component';
export * from './input/ui-input.component';
export * from './select/ui-select.component';
