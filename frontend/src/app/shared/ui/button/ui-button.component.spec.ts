/**
 * `UiButtonComponent` — Phase UI PR2 (task 2.2). Verifies the D57/D58
 * contract: a real native `<button>` (or `<a routerLink>` for `link`)
 * carries `data-testid`, never a wrapper or the component host, so every
 * existing `querySelectorAll('button')` + `.click()` page spec keeps
 * working after migration.
 */
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it } from 'vitest';

import { UiButtonComponent } from './ui-button.component';

@Component({
  imports: [UiButtonComponent],
  template: `
    <ui-button
      [variant]="variant()"
      [size]="size()"
      [block]="block()"
      [type]="type()"
      [disabled]="disabled()"
      [link]="link()"
      testId="my-button"
      (click)="onClick()"
    >
      Click me
    </ui-button>
  `,
})
class HostComponent {
  variant = signal<'primary' | 'secondary' | 'danger' | 'ghost'>('primary');
  size = signal<'sm' | 'md'>('md');
  block = signal(false);
  type = signal<'button' | 'submit'>('button');
  disabled = signal(false);
  link = signal<string | null>(null);
  clicks = 0;

  onClick(): void {
    this.clicks++;
  }
}

async function createFixture(): Promise<ComponentFixture<HostComponent>> {
  await TestBed.configureTestingModule({
    imports: [HostComponent],
    providers: [provideRouter([])],
  }).compileComponents();
  return TestBed.createComponent(HostComponent);
}

describe('UiButtonComponent', () => {
  it('renders a native <button> carrying the testid, not a wrapper', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const button = el.querySelector('[data-testid="my-button"]');
    expect(button).not.toBeNull();
    expect(button!.tagName).toBe('BUTTON');
    expect(button!.textContent?.trim()).toBe('Click me');
  });

  it('forwards type and reacts to a native click by bubbling to the host binding', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.type.set('submit');
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const button = el.querySelector('[data-testid="my-button"]') as HTMLButtonElement;
    expect(button.getAttribute('type')).toBe('submit');

    button.click();
    expect(fixture.componentInstance.clicks).toBe(1);
  });

  it('disabled suppresses the click — the handler never fires', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.disabled.set(true);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const button = el.querySelector('[data-testid="my-button"]') as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    button.click();
    expect(fixture.componentInstance.clicks).toBe(0);
  });

  it('renders an <a routerLink> instead of a <button> when link is set', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.link.set('/transfers/new');
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const anchor = el.querySelector('[data-testid="my-button"]');
    expect(anchor).not.toBeNull();
    expect(anchor!.tagName).toBe('A');
    expect(anchor!.getAttribute('href')).toBe('/transfers/new');
    expect(el.querySelector('button')).toBeNull();
  });

  it('applies distinct literal class strings per variant and per size', async () => {
    const fixture = await createFixture();
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const primaryClass = (el.querySelector('[data-testid="my-button"]') as HTMLElement).className;

    fixture.componentInstance.variant.set('danger');
    fixture.detectChanges();
    const dangerClass = (el.querySelector('[data-testid="my-button"]') as HTMLElement).className;

    expect(primaryClass).not.toBe(dangerClass);
    expect(primaryClass).toContain('bg-primary');
    expect(dangerClass).toContain('bg-danger');
  });

  it('adds a full-width class when block is true', async () => {
    const fixture = await createFixture();
    fixture.componentInstance.block.set(true);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    const button = el.querySelector('[data-testid="my-button"]') as HTMLElement;
    expect(button.className).toContain('w-full');
  });
});
