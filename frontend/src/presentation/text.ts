export function formatUiText(value: string): string {
  return value.replace(/[\u2013\u2014]/g, "-");
}
