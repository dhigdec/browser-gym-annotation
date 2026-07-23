import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/** Every component test mounts into the SAME document. Without this, a query in
 *  one test matches a pane another test left behind, and the failure surfaces on
 *  whichever test happened to run second. */
afterEach(cleanup);

/** jsdom has no layout engine and therefore no ResizeObserver. LiveBrowserPane
 *  observes its stage to fit the surface to the remote viewport's aspect, so
 *  without a stand-in the pane throws on mount and every component test fails
 *  for a reason that has nothing to do with the component. Nothing here reports
 *  a size: jsdom measures every box as zero, and the tests that care about
 *  geometry state the surface rect they are testing against explicitly. */
class UnmeasuredResizeObserver implements ResizeObserver {
  constructor(_onResize: ResizeObserverCallback) {}
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver ??= UnmeasuredResizeObserver;
