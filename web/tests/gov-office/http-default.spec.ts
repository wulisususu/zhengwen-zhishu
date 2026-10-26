import { expect, it } from "vitest";
import { getGovOfficeAdapter, setGovOfficeAdapter } from "../../src/features/gov-office/adapters";

it("uses real HTTP by default instead of in-memory demo data", () => {
  setGovOfficeAdapter(null);
  expect(getGovOfficeAdapter().mode).toBe("http");
});
