import createClient from "openapi-fetch";
import type { paths } from "./schema";

export type { components, operations, paths } from "./schema";

export function createApiClient(baseUrl = "") {
  return createClient<paths>({
    baseUrl,
    credentials: "include",
    cache: "no-store",
    headers: { "X-SallimBook-People": "1" },
  });
}
