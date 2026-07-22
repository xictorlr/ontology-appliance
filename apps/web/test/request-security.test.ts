import { describe, expect, it } from "vitest";
import { isSameOriginRequest } from "../lib/request-security";

describe("isSameOriginRequest", () => {
  it("accepts same-origin and non-browser requests", () => {
    expect(isSameOriginRequest(new Request("https://app.example/api/session"))).toBe(true);
    expect(
      isSameOriginRequest(
        new Request("https://app.example/api/session", {
          headers: { origin: "https://app.example", host: "app.example" },
        }),
      ),
    ).toBe(true);
  });

  it("uses trusted proxy host/protocol and rejects foreign origins", () => {
    const request = new Request("http://internal/api/session", {
      headers: {
        origin: "https://evil.example",
        host: "internal",
        "x-forwarded-host": "app.example",
        "x-forwarded-proto": "https",
      },
    });
    expect(isSameOriginRequest(request)).toBe(false);
  });

  it("rejects browser requests explicitly marked cross-site", () => {
    const request = new Request("https://app.example/api/session", {
      headers: { "sec-fetch-site": "cross-site" },
    });
    expect(isSameOriginRequest(request)).toBe(false);
  });
});
