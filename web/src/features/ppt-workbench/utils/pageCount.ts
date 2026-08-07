export const MIN_PPT_PAGE_COUNT = 3;
export const MAX_PPT_PAGE_COUNT = 12;
export const DEFAULT_PPT_PAGE_COUNT = 8;

export const pptPageCountOptions = Array.from(
  { length: MAX_PPT_PAGE_COUNT - MIN_PPT_PAGE_COUNT + 1 },
  (_, offset) => MIN_PPT_PAGE_COUNT + offset,
);

export function normalizePageCount(value: unknown, fallback = DEFAULT_PPT_PAGE_COUNT): number {
  const candidate = Number(value);
  if (Number.isInteger(candidate) && candidate >= MIN_PPT_PAGE_COUNT && candidate <= MAX_PPT_PAGE_COUNT) {
    return candidate;
  }
  return fallback;
}

export function parsePromptPageCount(prompt: string): number | undefined {
  const match = prompt.match(/(?:共|做|生成|制作|需要|要求)?\s*(\d{1,2}|[一二三四五六七八九十十二]+)\s*页/);
  if (!match) return undefined;
  const raw = match[1];
  const numeric = /^\d+$/.test(raw) ? Number(raw) : chinesePageCount(raw);
  return numeric >= MIN_PPT_PAGE_COUNT && numeric <= MAX_PPT_PAGE_COUNT ? numeric : undefined;
}

function chinesePageCount(value: string): number {
  const digits: Record<string, number> = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
  if (value === "十") return 10;
  if (value === "十二") return 12;
  if (value.length === 2 && value[0] === "十" && digits[value[1]]) return 10 + digits[value[1]];
  return digits[value] ?? 0;
}
