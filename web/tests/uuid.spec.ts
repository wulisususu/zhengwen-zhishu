import { describe, expect, it } from "vitest";
import { createClientUuid } from "../src/features/ppt-workbench/utils/uuid";

describe("createClientUuid", () => {
  it("uses randomUUID when the secure API is available", () => {
    expect(createClientUuid({
      randomUUID: () => "11111111-1111-4111-8111-111111111111",
      getRandomValues: (array) => array,
    })).toBe("11111111-1111-4111-8111-111111111111");
  });

  it("creates a valid v4 UUID from getRandomValues on an HTTP origin", () => {
    expect(createClientUuid({
      getRandomValues: (array) => {
        array.fill(0);
        return array;
      },
    })).toBe("00000000-0000-4000-8000-000000000000");
  });
});
