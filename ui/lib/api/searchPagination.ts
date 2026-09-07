// Pagination arithmetic for reference search results.

// The search route serves a fixed page size and accepts no override.
export const RESULTS_PER_PAGE = 20;

// What the window was before the API published it; servers predating the
// field still cap retrieval here.
const FALLBACK_MAX_RESULT_WINDOW = 10000;

export function resolveMaxResultWindow(maxResultWindow?: number): number {
  return maxResultWindow ?? FALLBACK_MAX_RESULT_WINDOW;
}

export function reachablePageCount(
  totalCount: number,
  maxResultWindow?: number,
): number {
  const window = resolveMaxResultWindow(maxResultWindow);
  return Math.ceil(Math.min(totalCount, window) / RESULTS_PER_PAGE);
}
