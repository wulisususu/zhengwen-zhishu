import { createMockGovOfficeAdapter } from "./MockGovOfficeAdapter";
import { HttpGovOfficeAdapter } from "./HttpGovOfficeAdapter";
import type { GovOfficeAdapter } from "./GovOfficeAdapter";

export type { DocumentQuery, GovOfficeAdapter } from "./GovOfficeAdapter";
export { GovOfficeError } from "./GovOfficeAdapter";

let instance: GovOfficeAdapter | null = null;

/**
 * Production uses the real government API. Demo data requires an explicit
 * VITE_GOV_OFFICE_MODE=demo build; network failure never selects the mock.
 */
export function getGovOfficeAdapter(): GovOfficeAdapter {
  if (!instance) instance = import.meta.env.VITE_GOV_OFFICE_MODE === "demo" ? createMockGovOfficeAdapter() : new HttpGovOfficeAdapter();
  return instance;
}

/** Test hook. */
export function setGovOfficeAdapter(adapter: GovOfficeAdapter | null): void {
  instance = adapter;
}
