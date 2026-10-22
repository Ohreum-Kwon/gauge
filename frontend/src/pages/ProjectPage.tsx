import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import ItemView from '../components/ItemView'
import type { ProjectSummary } from '../types'

export default function ProjectPage() {
  const projectId = Number(useParams().projectId)
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.project(projectId),
  })

  if (project.isPending) return <p className="muted">Loading…</p>
  if (project.error) return <p className="error">{project.error.message}</p>
  const p = project.data

  return (
    <>
      <Link to="/projects" className="muted">
        ← Projects
      </Link>
      <h1>{p.name}</h1>
      <dl className="stats">
        <Stat label="Items" value={p.item_count} />
        <Stat label="Gold items" value={p.gold_item_count} />
        <Stat label="Labels" value={p.label_count} />
        <Stat label="Gold rate" value={`${Math.round(p.gold_rate * 100)}%`} />
        <Stat label="Overlap rate" value={`${Math.round(p.overlap_rate * 100)}%`} />
      </dl>
      <p className="muted">Labels: {p.label_options.join(', ')}</p>
      <div className="columns">
        <UploadForm project={p} />
        <MembersForm projectId={p.id} />
      </div>
      <ItemsTable project={p} />
    </>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card">
      <dt className="muted">{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

function UploadForm({ project }: { project: ProjectSummary }) {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const upload = useMutation({
    mutationFn: (f: File) => api.uploadItems(project.id, f),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['project', project.id] })
      void queryClient.invalidateQueries({ queryKey: ['items', project.id] })
    },
  })
  const columns =
    project.task_type === 'image_classification'
      ? 'image_url, gold_answer'
      : 'prompt, response_a, response_b, gold_answer'

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (file) upload.mutate(file)
  }

  return (
    <form onSubmit={onSubmit} className="card stack">
      <h2>Upload items</h2>
      <p className="muted">
        CSV or JSON with columns <code>{columns}</code>. Rows with a gold_answer become gold items.
      </p>
      <input
        type="file"
        accept=".csv,.json"
        aria-label="Item file"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      {upload.error && <p className="error">{upload.error.message}</p>}
      {upload.data && (
        <p className="success">
          Added {upload.data.created} items ({upload.data.gold} gold).
        </p>
      )}
      <button type="submit" disabled={!file || upload.isPending}>
        Upload
      </button>
    </form>
  )
}

function MembersForm({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: ['users'], queryFn: () => api.users() })
  const members = useQuery({
    queryKey: ['members', projectId],
    queryFn: () => api.members(projectId),
  })
  const [selected, setSelected] = useState<Set<number> | null>(null)
  const save = useMutation({
    mutationFn: (ids: number[]) => api.setMembers(projectId, ids),
    onSuccess: (saved) => {
      queryClient.setQueryData(['members', projectId], saved)
      setSelected(null)
    },
  })

  if (!users.data || !members.data) return <div className="card">Loading members…</div>
  // Until the admin touches a checkbox, show the saved membership.
  const current = selected ?? new Set(members.data.map((m) => m.id))
  const candidates = users.data.filter((u) => u.role !== 'admin')

  function toggle(id: number) {
    const next = new Set(current)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  return (
    <div className="card stack">
      <h2>Members</h2>
      {candidates.map((u) => (
        <label key={u.id} className="checkbox">
          <input type="checkbox" checked={current.has(u.id)} onChange={() => toggle(u.id)} />
          {u.email} <span className="muted">({u.role})</span>
        </label>
      ))}
      {save.error && <p className="error">{save.error.message}</p>}
      <button
        type="button"
        disabled={selected === null || save.isPending}
        onClick={() => save.mutate([...current])}
      >
        Save members
      </button>
    </div>
  )
}

function ItemsTable({ project }: { project: ProjectSummary }) {
  const items = useQuery({ queryKey: ['items', project.id], queryFn: () => api.items(project.id) })
  if (!items.data?.length) return null

  return (
    <section>
      <h2>Items</h2>
      <p className="muted">
        Showing the first {items.data.length} of {project.item_count}.
      </p>
      <div className="item-grid">
        {items.data.map((item) => (
          <figure key={item.id} className="card">
            <ItemView taskType={project.task_type} payload={item.payload} size="thumb" />
            <figcaption>
              #{item.id}
              {item.gold_answer && <span className="badge">gold: {item.gold_answer}</span>}
              <span className="muted"> · {item.label_count} labels</span>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  )
}
