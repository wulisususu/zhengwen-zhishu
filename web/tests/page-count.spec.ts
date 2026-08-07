import { describe, expect, it } from "vitest";
import {
  DEFAULT_PPT_PAGE_COUNT,
  MAX_PPT_PAGE_COUNT,
  MIN_PPT_PAGE_COUNT,
  normalizePageCount,
  parsePromptPageCount,
  pptPageCountOptions,
} from "../src/features/ppt-workbench/utils/pageCount";

describe("PPT page count selection", () => {
  it("offers exactly 3 through 12 pages and defaults to 8", () => {
    expect(pptPageCountOptions).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(normalizePageCount(undefined)).toBe(DEFAULT_PPT_PAGE_COUNT);
    expect(MIN_PPT_PAGE_COUNT).toBe(3);
    expect(MAX_PPT_PAGE_COUNT).toBe(12);
  });

  it("recognizes Arabic and Chinese page counts in a prompt", () => {
    expect(parsePromptPageCount("做一个保护环境的5页PPT")).toBe(5);
    expect(parsePromptPageCount("制作一份十二页的汇报")).toBe(12);
  });
});
