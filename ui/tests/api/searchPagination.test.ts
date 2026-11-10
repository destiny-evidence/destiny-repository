import {
  reachablePageCount,
  resolveMaxResultWindow,
} from "@/api/searchPagination";

describe("search pagination", () => {
  it("falls back to the historic window when the API omits it", () => {
    expect(resolveMaxResultWindow()).toBe(10000);
    expect(resolveMaxResultWindow(500)).toBe(500);
  });

  it("rounds partial pages up", () => {
    expect(reachablePageCount(41)).toBe(3);
    expect(reachablePageCount(0)).toBe(0);
  });

  it("caps pages at the result window", () => {
    expect(reachablePageCount(1_000_000)).toBe(500);
    expect(reachablePageCount(1_000_000, 100)).toBe(5);
  });
});
