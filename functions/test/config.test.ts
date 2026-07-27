import { describe, expect, it } from "vitest";

import { REGION, TASK_REGION } from "../src/config";

describe("regional deployment contract", () => {
  it("keeps data events in europe-west4 and Cloud Tasks in a supported EU region", () => {
    expect(REGION).toBe("europe-west4");
    expect(TASK_REGION).toBe("europe-west1");
  });
});
