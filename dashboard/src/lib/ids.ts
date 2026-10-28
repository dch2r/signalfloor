const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Run ids come from the URL, so check them before they reach the API. */
export function isRunId(value: string | string[] | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}
