/**
 * Placement for a confidence interval drawn on a horizontal axis centred on zero.
 *
 * The axis runs from -extent to +extent so that zero always sits in the middle. Whether the
 * interval crosses zero is the whole point of the picture, so zero must be easy to find.
 */
export function axisExtent(values: number[]): number {
  const largest = Math.max(...values.map(Math.abs));
  // A little room past the largest value. A flat axis if everything is zero.
  return largest > 0 ? largest * 1.15 : 1;
}

/** Position of a value on the axis, from 0 (left edge) to 100 (right edge). */
export function toPercent(value: number, extent: number): number {
  const percent = 50 + (value / extent) * 50;
  return Math.min(100, Math.max(0, percent));
}
