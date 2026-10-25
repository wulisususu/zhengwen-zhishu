import { createMockGovOfficeAdapter } from "./MockGovOfficeAdapter";
import type { GovOfficeAdapter } from "./GovOfficeAdapter";

export type { DocumentQuery, GovOfficeAdapter } from "./GovOfficeAdapter";
export { GovOfficeError } from "./GovOfficeAdapter";

let instance: GovOfficeAdapter | null = null;

/**
 * Only the mock adapter exists: the backend endpoints for policy QA, drafting,
 * proofreading and review are not defined yet. Add an HTTP adapter here once
 * they are; do not point the UI at guessed endpoints.
 */
export function getGovOfficeAdapter(): GovOfficeAdapter {
  if (!instance) instance = createMockGovOfficeAdapter();
  return instance;
}

/** Test hook. */
export function setGovOfficeAdapter(adapter: GovOfficeAdapter | null): void {
  instance = adapter;
}
