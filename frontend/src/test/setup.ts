import "@testing-library/jest-dom";

// jsdom has no layout observer; real geometry is checked in browser acceptance.
globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
