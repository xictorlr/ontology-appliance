type FirebaseSessionUser = {
  getIdToken(forceRefresh?: boolean): Promise<string>;
};

type SessionProblem = {
  type?: string;
  detail?: string;
};

const enrollmentRefreshProblem =
  "urn:ontology-appliance:problem:membership-token-refresh-required";

export async function createFirebaseSession(
  user: FirebaseSessionUser,
  request: typeof fetch = fetch,
): Promise<void> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = await request("/api/session", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ idToken: await user.getIdToken(true) }),
    });
    if (response.ok) return;

    const problem = await response.json().catch(() => null) as SessionProblem | null;
    if (
      attempt === 0 &&
      response.status === 409 &&
      problem?.type === enrollmentRefreshProblem
    ) {
      continue;
    }
    throw new Error(problem?.detail ?? "Could not create a secure session.");
  }
}
