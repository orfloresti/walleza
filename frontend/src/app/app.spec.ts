import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
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
            },
          },
          translocoConfig: { availableLangs: ['en', 'es'], defaultLang: 'en' },
          preloadLangs: true,
        }),
      ],
      providers: [provideRouter([])],
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
});
