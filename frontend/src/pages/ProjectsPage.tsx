import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import type { Project, ProjectCreate, TaskType } from '../types'

const TASK_TYPE_NAMES: Record<TaskType, string> = {
  image_classification: 'Image classification',
  pairwise_preference: 'Pairwise preference',
}

export default function ProjectsPage() {
  const { user } = useAuth()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })

  return (
    <>
      <h1>Projects</h1>
      {projects.isPending && <p className="muted">Loading…</p>}
      {projects.error && <p className="error">{projects.error.message}</p>}
      {projects.data?.length === 0 && (
        <p className="muted">
          {user?.role === 'admin'
            ? 'No projects yet. Create one below.'
            : "You haven't been added to a project yet."}
        </p>
      )}
      <ul className="project-list">
        {projects.data?.map((project) => (
          <ProjectRow key={project.id} project={project} />
        ))}
      </ul>
      {user?.role === 'admin' && <NewProjectForm />}
    </>
  )
}

function ProjectRow({ project }: { project: Project }) {
  const { user } = useAuth()
  return (
    <li className="card row">
      <div>
        <strong>{project.name}</strong>
        <div className="muted">
          {TASK_TYPE_NAMES[project.task_type]} · {project.label_options.length} labels
        </div>
      </div>
      {(user?.role === 'admin' || user?.role === 'reviewer') && (
        <nav className="links">
          <Link to={`/projects/${project.id}/quality`}>Quality</Link>
          <Link to={`/projects/${project.id}/review`}>Review</Link>
          {user.role === 'admin' && <Link to={`/projects/${project.id}`}>Manage</Link>}
        </nav>
      )}
      {user?.role === 'labeler' && (
        <Link className="button" to={`/projects/${project.id}/label`}>
          Start labeling
        </Link>
      )}
    </li>
  )
}

type Settings = Pick<
  ProjectCreate,
  'gold_rate' | 'overlap_rate' | 'overlap_labelers' | 'target_error_rate'
>

const DEFAULT_SETTINGS: Settings = {
  gold_rate: 0.1,
  overlap_rate: 0.1,
  overlap_labelers: 3,
  target_error_rate: 0.1,
}

const SETTING_FIELDS: {
  key: keyof Settings
  label: string
  help: string
  min: number
  max: number
  step: number
}[] = [
  {
    key: 'gold_rate',
    label: 'Gold rate',
    help: 'Share of each queue drawn from gold items with known answers',
    min: 0,
    max: 1,
    step: 0.05,
  },
  {
    key: 'overlap_rate',
    label: 'Overlap rate',
    help: 'Share of items labeled by several people, for agreement',
    min: 0,
    max: 1,
    step: 0.05,
  },
  {
    key: 'overlap_labelers',
    label: 'Labelers per overlap item',
    help: 'How many people label each overlap item',
    min: 2,
    max: 20,
    step: 1,
  },
  {
    key: 'target_error_rate',
    label: 'Target error rate',
    help: 'Acceptable gold error rate: the center line of each control chart',
    min: 0.01,
    max: 0.99,
    step: 0.01,
  },
]

function NewProjectForm() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [taskType, setTaskType] = useState<TaskType>('image_classification')
  const [options, setOptions] = useState('')
  const [settings, setSettings] = useState(DEFAULT_SETTINGS)

  const create = useMutation({
    mutationFn: api.createProject,
    onSuccess: (project) => {
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${project.id}`)
    },
  })

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    create.mutate({
      name,
      task_type: taskType,
      label_options: options
        .split(',')
        .map((o) => o.trim())
        .filter(Boolean),
      ...settings,
    })
  }

  return (
    <form onSubmit={onSubmit} className="card stack">
      <h2>New project</h2>
      <label>
        Name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label>
        Task type
        <select value={taskType} onChange={(e) => setTaskType(e.target.value as TaskType)}>
          {Object.entries(TASK_TYPE_NAMES).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Label options, separated by commas
        <input
          value={options}
          onChange={(e) => setOptions(e.target.value)}
          placeholder={taskType === 'pairwise_preference' ? 'A, B' : 'cat, dog, bird'}
          required
        />
      </label>
      <div className="settings">
        {SETTING_FIELDS.map((field) => (
          <label key={field.key} title={field.help}>
            {field.label}
            <input
              type="number"
              min={field.min}
              max={field.max}
              step={field.step}
              value={settings[field.key]}
              onChange={(e) => setSettings({ ...settings, [field.key]: Number(e.target.value) })}
            />
          </label>
        ))}
      </div>
      {create.error && <p className="error">{create.error.message}</p>}
      <button type="submit" disabled={create.isPending}>
        Create project
      </button>
    </form>
  )
}
