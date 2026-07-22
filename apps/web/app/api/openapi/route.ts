import { readFile } from "node:fs/promises";
import path from "node:path";

export async function GET() {
  const contractPath = path.resolve(process.cwd(), "../../contracts/openapi.yaml");
  const contract = await readFile(contractPath, "utf8");
  return new Response(contract, {
    headers: {
      "content-type": "application/yaml; charset=utf-8",
      "cache-control": "public, max-age=300",
    },
  });
}
