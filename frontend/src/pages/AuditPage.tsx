import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'

const PAGE_SIZE = 50

const ACTIONS = ['user.create', 'project.create', 'items.upload', 'label.create', 'item.resolve']

export default function AuditPage() {
  const [action, setAction] = useState('')
  const [offset, setOffset] = useState(0)
  const page = useQuery({
    queryKey: ['audit', action, offset],
    queryFn: () => api.audit(offset, action || undefined),
    placeholderData: keepPreviousData,
  })

  return (
    <>
      <h1>Audit log</h1>
      <p className="muted">
        Every change to projects, items, labels and resolutions, newest first.
      </p>
      <div className="filters">
        <label>
          Action
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value)
              setOffset(0)
            }}
          >
            <option value="">All actions</option>
            {ACTIONS.map((a) => (
              <option key={a}>{a}</option>
            ))}
          </select>
        </label>
      </div>
      {page.isPending && <p className="muted">Loading…</p>}
      {page.error && <p className="error">{page.error.message}</p>}
      {page.data && (
        <>
          <div className="card table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Who</th>
                  <th>Action</th>
                  <th>Target</th>
                  <th>Change</th>
                </tr>
              </thead>
              <tbody>
                {page.data.entries.map((e) => (
                  <tr key={e.id}>
                    <td className="nowrap">
                      {new Date(e.created_at).toLocaleString(undefined, {
                        dateStyle: 'short',
                        timeStyle: 'short',
                      })}
                    </td>
                    <td>{e.actor_email ?? <span className="muted">deleted user</span>}</td>
                    <td>
                      <code>{e.action}</code>
                    </td>
                    <td className="nowrap">
                      {e.target_type} {e.target_id !== null && `#${e.target_id}`}
                    </td>
                    <td className="diff">
                      {e.before && <div className="muted">before {JSON.stringify(e.before)}</div>}
                      {e.after && <div>{JSON.stringify(e.after)}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <button
              type="button"
              className="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Newer
            </button>
            <span className="muted">
              {page.data.total === 0
                ? 'No entries'
                : `${offset + 1}–${offset + page.data.entries.length} of ${page.data.total}`}
            </span>
            <button
              type="button"
              className="secondary"
              disabled={offset + PAGE_SIZE >= page.data.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Older
            </button>
          </div>
        </>
      )}
    </>
  )
}
