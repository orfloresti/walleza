import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { TranslocoTestingModule } from '@jsverse/transloco';
import { App } from './app';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [
        App,
        TranslocoTestingModule.forRoot({
          langs: {
            en: {
              accounts: { title: 'Accounts' },
              transactions: { title: 'Transactions' },
              categories: { title: 'Categories' },
              transfers: { title: 'Transfers' },
              templates: { title: 'Templates' },
              recurring: { title: 'Recurring transactions' },
              workspace: { title: 'Workspace' },
              common: { menu: { toggle: 'Menu' } },
            },
          },
          translocoConfig: { availableLangs: ['en', 'es'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideRouter([{ path: 'accounts', component: App }])],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render a router outlet', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('router-outlet')).toBeTruthy();
  });

  it('should render a nav link to every top-level feature', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const hrefs = Array.from(compiled.querySelectorAll('nav a')).map((a) =>
      a.getAttribute('href'),
    );
    expect(hrefs).toEqual([
      '/accounts',
      '/transactions',
      '/categories',
      '/transfers',
      '/templates',
      '/recurring',
      '/workspace',
    ]);
  });

  it('keeps rendering all 7 nav links whether the mobile menu is open or closed (D61)', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;

    const expectedHrefs = [
      '/accounts',
      '/transactions',
      '/categories',
      '/transfers',
      '/templates',
      '/recurring',
      '/workspace',
    ];

    const closedHrefs = Array.from(compiled.querySelectorAll('nav a')).map((a) =>
      a.getAttribute('href'),
    );
    expect(closedHrefs).toEqual(expectedHrefs);

    app.menuOpen.set(true);
    fixture.detectChanges();

    const openHrefs = Array.from(compiled.querySelectorAll('nav a')).map((a) =>
      a.getAttribute('href'),
    );
    expect(openHrefs).toEqual(expectedHrefs);
  });

  it('toggles aria-expanded on the mobile nav menu toggle', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    const toggle = compiled.querySelector(
      '[data-testid="nav-menu-toggle"]',
    ) as HTMLButtonElement;

    expect(toggle).toBeTruthy();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');

    toggle.click();
    fixture.detectChanges();
    expect(toggle.getAttribute('aria-expanded')).toBe('true');

    toggle.click();
    fixture.detectChanges();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
  });

  it('closes the mobile nav menu on NavigationEnd', async () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    fixture.detectChanges();

    app.menuOpen.set(true);
    fixture.detectChanges();
    expect(app.menuOpen()).toBe(true);

    const router = TestBed.inject(Router);
    await router.navigateByUrl('/accounts');
    fixture.detectChanges();

    expect(app.menuOpen()).toBe(false);
  });
});
