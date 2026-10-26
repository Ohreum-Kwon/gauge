export const percent = (value: number | null | undefined, digits = 0) =>
  value === null || value === undefined ? '–' : `${(value * 100).toFixed(digits)}%`

export const seconds = (ms: number | null) => (ms === null ? '–' : `${(ms / 1000).toFixed(1)} s`)

export const kappa = (value: number | null) => (value === null ? '–' : value.toFixed(2))
