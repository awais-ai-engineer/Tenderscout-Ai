export function date(value: string | null | undefined, time = false) {
  if (!value) return "Not provided";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return (
    new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
      ...(time ? ({ hour: "2-digit", minute: "2-digit" } as const) : {}),
    }).format(parsed) + (time ? " UTC" : "")
  );
}
export function label(value: string) {
  return value.replace(/[_-]/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
export function source(value: string) {
  return value === "contracts-finder"
    ? "Contracts Finder"
    : value === "find-a-tender"
      ? "Find a Tender"
      : value === "ted"
        ? "TED"
        : value;
}
export function positive(
  value: string | string[] | undefined,
): number | undefined {
  const n = Number(value);
  return Number.isSafeInteger(n) && n > 0 ? n : undefined;
}
