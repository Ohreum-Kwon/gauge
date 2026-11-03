import type { LabelerStatus, PanelStatus } from '../types'

const STATUS: Record<LabelerStatus | PanelStatus, { icon: string; label: string; tone: string }> = {
  in_control: { icon: '✓', label: 'In control', tone: 'good' },
  warning: { icon: '~', label: 'Warning', tone: 'warning' },
  out_of_control: { icon: '!', label: 'Out of control', tone: 'critical' },
  insufficient_data: { icon: '?', label: 'Not enough gold', tone: 'unknown' },
}

/** A control-chart status: color, icon and word together, never color alone. */
export default function StatusBadge({ status }: { status: LabelerStatus | PanelStatus }) {
  const { icon, label, tone } = STATUS[status]
  return (
    <span className="status">
      <span className={`status-icon ${tone}`} aria-hidden>
        {icon}
      </span>
      {label}
    </span>
  )
}
