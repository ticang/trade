import "@testing-library/jest-dom/vitest";

// jsdom lacks ResizeObserver; recharts ResponsiveContainer depends on it.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver =
  ResizeObserverStub;
