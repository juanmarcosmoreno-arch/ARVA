import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { forgetFlyeChoices } from "@/lib/flye";

afterEach(() => {
  cleanup();
  // Choices remembered by "New assembly" for the session must not leak from one test into the next.
  forgetFlyeChoices();
});

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
});
