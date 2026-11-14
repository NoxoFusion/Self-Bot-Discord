import '@testing-library/jest-dom';

// jsdom does not implement ResizeObserver. The shared design-mode protocol
// uses it to re-sync the selection overlay on layout changes.
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }

  globalThis.ResizeObserver =
    ResizeObserverMock as unknown as typeof ResizeObserver;
}
