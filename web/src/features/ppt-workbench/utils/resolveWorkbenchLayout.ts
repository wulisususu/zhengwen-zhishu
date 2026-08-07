// Pure, framework-agnostic resolver for the PPT workbench responsive layout.
// Keeps the chat / slide-rail / editor columns from overflowing at common
// enterprise resolutions (1600+, 1280-1600, 1024-1280, <1024). The editor
// content column itself is `minmax(0, 1fr)` in CSS so it can shrink; this
// helper only caps the two side panels to a sane share of the viewport.

export type WorkbenchLayoutTier = "wide" | "standard" | "narrow" | "compact";

export interface WorkbenchLayout {
  tier: WorkbenchLayoutTier;
  /** Max chat-panel width (px) the viewport can comfortably host. */
  maxChat: number;
  /** Max slide-rail width (px) the viewport can comfortably host. */
  maxRail: number;
  /** Whether the three columns should stack / collapse on very small screens. */
  stack: boolean;
}

const guard = (width: number): number =>
  Number.isFinite(width) && width > 0 ? width : 1440;

export function resolveWorkbenchLayout(width: number): WorkbenchLayout {
  const w = guard(width);
  if (w >= 1600) {
    return { tier: "wide", maxChat: 520, maxRail: 240, stack: false };
  }
  if (w >= 1280) {
    return { tier: "standard", maxChat: 440, maxRail: 210, stack: false };
  }
  if (w >= 1024) {
    return { tier: "narrow", maxChat: 360, maxRail: 180, stack: false };
  }
  return { tier: "compact", maxChat: 320, maxRail: 160, stack: true };
}
