"use strict";

const assert = require("node:assert/strict");
const { Client } = require("firebase-tools/lib/apiv2");

async function main() {
  let observedRequest;
  const originalPost = Client.prototype.post;

  Client.prototype.post = async (path, body) => {
    observedRequest = { path, body };
    return { body: { bindings: [] } };
  };

  try {
    const resourceManager = require("firebase-tools/lib/gcp/resourceManager");
    await resourceManager.getIamPolicy("test-project-number");
  } finally {
    Client.prototype.post = originalPost;
  }

  assert.deepEqual(observedRequest, {
    path: "/projects/test-project-number:getIamPolicy",
    body: {
      options: {
        requestedPolicyVersion: 3,
      },
    },
  });

  console.log("Firebase CLI conditional IAM policy support: ok");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
