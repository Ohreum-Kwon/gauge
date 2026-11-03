import type { PanelChart } from './types'

export const percent = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined ? '–' : `${(value * 100).toFixed(digits)}%`

export const seconds = (ms: number | null) => (ms === null ? '–' : `${(ms / 1000).toFixed(1)} s`)

export const kappa = (value: number | null) => (value === null ? '–' : value.toFixed(2))

/** Decimal places that resolve the control band: 0 for luminance, 3 for Vth. */
export function digitsFor(chart: PanelChart) {
  const span = chart.xbar_ucl - chart.xbar_lcl
  return Math.min(4, Math.max(0, 1 - Math.floor(Math.log10(span || 1))))
}
