import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';
import { SwUpdate, VersionEvent } from '@angular/service-worker';
import { interval } from 'rxjs';

/**
 * Design D6a: poll for a new shell version every 6 hours and whenever
 * the tab regains focus, in addition to the check the service worker
 * itself performs on registration.
 */
const POLL_INTERVAL_MS = 6 * 60 * 60 * 1000;

/**
 * Drives the "defined update-and-reload flow" the pwa-shell spec
 * requires: a `VERSION_READY` event surfaces as a non-blocking signal a
 * toast component can render, `activateUpdate()` swaps in the new
 * version and reloads, and an `unrecoverable` service-worker state
 * forces a hard reload since the running app can no longer be trusted
 * (design D6a).
 */
@Injectable({ providedIn: 'root' })
export class AppUpdateService {
  private readonly swUpdate = inject(SwUpdate);
  private readonly document = inject(DOCUMENT);

  /** Set to `true` on `VERSION_READY`; a toast component reads this to prompt reload. */
  readonly updateAvailable = signal(false);

  private initialized = false;

  /** Wires the subscriptions and polling below. Call once at bootstrap. */
  init(): void {
    if (this.initialized || !this.swUpdate.isEnabled) {
      return;
    }
    this.initialized = true;

    this.swUpdate.versionUpdates.subscribe((event: VersionEvent) => {
      if (event.type === 'VERSION_READY') {
        this.updateAvailable.set(true);
      }
    });

    this.swUpdate.unrecoverable.subscribe(() => {
      this.document.location.reload();
    });

    void this.checkForUpdate();
    interval(POLL_INTERVAL_MS).subscribe(() => void this.checkForUpdate());
    this.document.defaultView?.addEventListener('focus', () => void this.checkForUpdate());
  }

  /** Best-effort: a failed check is simply retried on the next interval/focus. */
  async checkForUpdate(): Promise<void> {
    if (!this.swUpdate.isEnabled) {
      return;
    }
    try {
      await this.swUpdate.checkForUpdate();
    } catch {
      // Intentionally swallowed — see the doc comment above.
    }
  }

  /** Invoked from the non-blocking update toast's "reload" action. */
  async activateUpdate(): Promise<void> {
    await this.swUpdate.activateUpdate();
    this.document.location.reload();
  }
}
