import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { filter } from 'rxjs';

/**
 * Design D61 — one link list, rendered exactly once, whose *visibility*
 * (never its existence) is toggled by `menuOpen`. Navigating anywhere
 * closes the mobile menu, so it never stays open across route changes.
 */
@Component({
  imports: [RouterOutlet, RouterLink, RouterLinkActive, TranslocoPipe],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  private readonly router = inject(Router);

  readonly menuOpen = signal(false);

  constructor() {
    this.router.events
      .pipe(
        filter((event): event is NavigationEnd => event instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.menuOpen.set(false));
  }
}
