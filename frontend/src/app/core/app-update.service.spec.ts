/**
 * Design D6a: `SwUpdate.versionUpdates` -> `VERSION_READY` surfaces a
 * non-blocking update signal; `activateUpdate()` swaps in the new
 * version and reloads; an `unrecoverable` service-worker state forces a
 * hard reload. Exercises the real `AppUpdateService` against a stub
 * `SwUpdate` (the real class talks to an actual registered service
 * worker, which does not exist in this unit-test environment).
 */

import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { SwUpdate, UnrecoverableStateEvent, VersionEvent } from '@angular/service-worker';
import { Subject } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppUpdateService } from './app-update.service';

class StubSwUpdate {
  readonly versionUpdates = new Subject<VersionEvent>();
  readonly unrecoverable = new Subject<UnrecoverableStateEvent>();
  isEnabled = true;
  checkForUpdate = vi.fn().mockResolvedValue(false);
  activateUpdate = vi.fn().mockResolvedValue(true);
}

describe('AppUpdateService', () => {
  let stubSwUpdate: StubSwUpdate;
  let reloadSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    stubSwUpdate = new StubSwUpdate();
    reloadSpy = vi.fn();

    TestBed.configureTestingModule({
      providers: [
        { provide: SwUpdate, useValue: stubSwUpdate },
        {
          provide: DOCUMENT,
          useValue: { location: { reload: reloadSpy }, defaultView: window },
        },
      ],
    });
  });

  it('does nothing when the service worker is not enabled', () => {
    stubSwUpdate.isEnabled = false;
    const service = TestBed.inject(AppUpdateService);

    service.init();

    expect(stubSwUpdate.checkForUpdate).not.toHaveBeenCalled();
  });

  it('flags updateAvailable when a VERSION_READY event arrives', () => {
    const service = TestBed.inject(AppUpdateService);

    service.init();
    expect(service.updateAvailable()).toBe(false);

    stubSwUpdate.versionUpdates.next({
      type: 'VERSION_READY',
      currentVersion: { hash: 'old' },
      latestVersion: { hash: 'new' },
    });

    expect(service.updateAvailable()).toBe(true);
  });

  it('reloads on an unrecoverable service-worker state', () => {
    const service = TestBed.inject(AppUpdateService);

    service.init();
    stubSwUpdate.unrecoverable.next({
      type: 'UNRECOVERABLE_STATE',
      reason: 'cache corrupted',
    });

    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it('activateUpdate() activates the new version then reloads', async () => {
    const service = TestBed.inject(AppUpdateService);

    await service.activateUpdate();

    expect(stubSwUpdate.activateUpdate).toHaveBeenCalledTimes(1);
    expect(reloadSpy).toHaveBeenCalledTimes(1);
  });

  it('checkForUpdate() calls through to SwUpdate.checkForUpdate()', async () => {
    const service = TestBed.inject(AppUpdateService);

    await service.checkForUpdate();

    expect(stubSwUpdate.checkForUpdate).toHaveBeenCalledTimes(1);
  });
});
