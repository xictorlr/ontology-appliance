import { describe, expect, it, vi } from "vitest";
import { createFirebaseSession } from "../lib/session-client";

describe("createFirebaseSession", () => {
  it("refreshes the ID token once after automatic enrollment", async () => {
    const user = {
      getIdToken: vi.fn()
        .mockResolvedValueOnce("before-enrollment")
        .mockResolvedValueOnce("after-enrollment"),
    };
    const request = vi.fn()
      .mockResolvedValueOnce(
        Response.json(
          {
            type: "urn:ontology-appliance:problem:membership-token-refresh-required",
            detail: "Refresh the identity token.",
          },
          { status: 409 },
        ),
      )
      .mockResolvedValueOnce(Response.json({ ok: true }));

    await createFirebaseSession(user, request);

    expect(user.getIdToken).toHaveBeenCalledTimes(2);
    expect(request).toHaveBeenCalledTimes(2);
    const secondRequest = request.mock.calls[1]?.[1] as RequestInit | undefined;
    expect(JSON.parse(String(secondRequest?.body))).toEqual({
      idToken: "after-enrollment",
    });
  });

  it("surfaces membership errors without retrying indefinitely", async () => {
    const user = { getIdToken: vi.fn().mockResolvedValue("token") };
    const request = vi.fn().mockResolvedValue(
      Response.json({ detail: "Membership is not available." }, { status: 403 }),
    );

    await expect(createFirebaseSession(user, request)).rejects.toThrow(
      "Membership is not available.",
    );
    expect(request).toHaveBeenCalledTimes(1);
  });
});
