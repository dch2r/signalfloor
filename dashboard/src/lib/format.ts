const dateFormat = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

/** A timestamp from the API, shown in UTC so the server and the browser render the same text. */
export function formatDate(iso: string): string {
  return `${dateFormat.format(new Date(iso))} UTC`;
}

export function formatScore(score: number): string {
  return score.toFixed(3);
}

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

/** A change in score with its sign, like +0.083 or -0.105. */
export function formatDelta(delta: number): string {
  const text = Math.abs(delta).toFixed(3);
  if (text === "0.000") return "0.000";
  return `${delta > 0 ? "+" : "-"}${text}`;
}
