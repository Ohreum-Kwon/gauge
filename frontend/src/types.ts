// Mirrors the API schemas in backend/app/schemas.py.

export type Role = 'admin' | 'labeler' | 'reviewer'
export type TaskType = 'image_classification' | 'pairwise_preference'

export interface User {
  id: number
  email: string
  role: Role
  created_at: string
}

export interface Project {
  id: number
  name: string
  task_type: TaskType
  label_options: string[]
  gold_rate: number
  overlap_rate: number
  overlap_labelers: number
  target_error_rate: number
  created_at: string
}

export interface ProjectSummary extends Project {
  item_count: number
  gold_item_count: number
  label_count: number
}

export interface ProjectCreate {
  name: string
  task_type: TaskType
  label_options: string[]
  gold_rate: number
  overlap_rate: number
  overlap_labelers: number
  target_error_rate: number
}

export interface Item {
  id: number
  payload: Record<string, string>
  gold_answer: string | null
  label_count: number
}

export interface Task {
  assignment_id: number
  project_id: number
  task_type: TaskType
  label_options: string[]
  item: { id: number; payload: Record<string, string> }
}

export interface Progress {
  completed: number
  remaining: number
}

export interface UploadResult {
  created: number
  gold: number
}

export interface GoldAccuracy {
  gold_answered: number
  gold_correct: number
  accuracy: number | null
}

export type LabelerStatus = 'in_control' | 'out_of_control' | 'insufficient_data'

export interface Alert {
  day: string
  rule: string
  description: string
  above: boolean
}

export interface LabelerQuality {
  user_id: number
  email: string
  labels: number
  gold_answered: number
  gold_correct: number
  accuracy: number | null
  median_time_ms: number | null
  fast_share: number | null
  status: LabelerStatus
  latest_alert: Alert | null
}

export interface ProjectQuality {
  target_error_rate: number
  labelers: LabelerQuality[]
  agreement: {
    fleiss_kappa: number | null
    overlap_items: number
    raters_per_item: number
    pairs: { user_a: number; user_b: number; kappa: number | null; shared_items: number }[]
  }
}

export interface ChartPoint {
  day: string
  gold_answered: number
  errors: number
  error_rate: number
  ucl: number
  lcl: number
}

export interface ControlChart {
  user_id: number
  center: number
  points: ChartPoint[]
  alerts: Alert[]
}

export interface ReviewItem {
  id: number
  payload: Record<string, string>
  reasons: ('disagreement' | 'flagged_labeler')[]
  labels: { user_id: number; email: string; value: string; flagged: boolean }[]
}

export interface ReviewQueue {
  total: number
  items: ReviewItem[]
}

export interface AuditEntry {
  id: number
  actor_email: string | null
  action: string
  target_type: string
  target_id: number | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  created_at: string
}

export interface AuditPage {
  total: number
  entries: AuditEntry[]
}

export type PanelStatus = 'in_control' | 'warning' | 'out_of_control'

export interface PanelMetric {
  key: string
  name: string
  unit: string
  group: 'optical' | 'electrical'
  target: number
  lsl: number | null
  usl: number | null
}

export interface PanelSignal {
  subgroup: number
  measured_at: string
  rule: string
  description: string
  severity: 'alarm' | 'warning'
  above: boolean
}

export interface PanelSeriesSummary {
  line: string
  metric: string
  status: PanelStatus
  first_warning: PanelSignal | null
  first_alarm: PanelSignal | null
  signals: number
  latest_mean: number
  baseline_cpk: number
  recent_cpk: number
}

export interface PanelLineSummary {
  baseline_subgroups: number
  lines: string[]
  metrics: PanelMetric[]
  series: PanelSeriesSummary[]
}

export interface Capability {
  mean: number
  sigma_within: number
  sigma_overall: number
  cp: number | null
  cpk: number
  pp: number | null
  ppk: number
}

export interface PanelChartPoint {
  subgroup: number
  measured_at: string
  lot: string
  mean: number
  range: number
  z: number
  ewma: number
  ewma_ucl: number
  ewma_lcl: number
}

export interface PanelChart {
  line: string
  metric: PanelMetric
  status: PanelStatus
  baseline_subgroups: number
  subgroup_size: number
  center: number
  xbar_ucl: number
  xbar_lcl: number
  r_center: number
  r_ucl: number
  r_lcl: number
  points: PanelChartPoint[]
  signals: PanelSignal[]
  baseline_capability: Capability
  recent_capability: Capability
}
