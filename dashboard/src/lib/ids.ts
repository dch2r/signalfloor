/** URL parameters for the compare pages, checked before they reach the API. */

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Run ids come from the URL, so check them before they reach the API. */
export function isRunId(value: string | string[] | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

/** undefined when no margin was given, null when the one given isn't usable. */
export function parseMargin(value: string | string[] | undefined): number | undefined | null {
  if (value === undefined || value === "") return undefined;
  if (typeof value !== "string") return null;
  const margin = Number(value);
  return Number.isFinite(margin) && margin >= 0 ? margin : null;
}
