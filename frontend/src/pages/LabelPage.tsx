import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import ItemView from '../components/ItemView'
import type { Task } from '../types'

// Keys 1–9 then 0 pick the first ten options.
const SHORTCUT_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']

const now = () => performance.now()

export default function LabelPage() {
  const projectId = Number(useParams().projectId)
  const queryClient = useQueryClient()
  const task = useQuery({
    queryKey: ['task', projectId],
    queryFn: () => api.nextTask(projectId),
    staleTime: Infinity,
  })
  const progress = useQuery({
    queryKey: ['progress', projectId],
    queryFn: () => api.progress(projectId),
  })

  const submit = useMutation({
    mutationFn: ({ t, value, ms }: { t: Task; value: string; ms: number }) =>
      api.submitLabel(t.assignment_id, value, ms),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['task', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['progress', projectId] })
    },
  })

  if (task.isPending) return <p className="muted">Loading…</p>
  if (task.error) return <p className="error">{task.error.message}</p>

  const done = progress.data ? progress.data.completed : 0
  const total = progress.data ? progress.data.completed + progress.data.remaining : 0

  return (
    <>
      <div className="row">
        <Link to="/projects" className="muted">
          ← Projects
        </Link>
        {total > 0 && (
          <span className="muted" aria-label="progress">
            {done} / {total} labeled
          </span>
        )}
      </div>
      {total > 0 && <progress value={done} max={total} />}
      {task.data === null ? (
        <div className="card">
          <h2>All done</h2>
          <p className="muted">There's nothing left to label in this project.</p>
        </div>
      ) : (
        <TaskCard
          key={task.data.assignment_id}
          task={task.data}
          disabled={submit.isPending}
          onLabel={(value, ms) => submit.mutate({ t: task.data!, value, ms })}
        />
      )}
      {submit.error && <p className="error">{submit.error.message}</p>}
    </>
  )
}

function TaskCard({
  task,
  disabled,
  onLabel,
}: {
  task: Task
  disabled: boolean
  onLabel: (value: string, timeSpentMs: number) => void
}) {
  // Time on task: from when the item is shown to when a label is picked.
  const [shownAt] = useState(now)
  const pick = useCallback(
    (value: string) => onLabel(value, Math.round(now() - shownAt)),
    [onLabel, shownAt],
  )

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (disabled || event.metaKey || event.ctrlKey || event.altKey) return
      const index = SHORTCUT_KEYS.indexOf(event.key)
      if (index >= 0 && index < task.label_options.length) pick(task.label_options[index])
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [task, disabled, pick])

  return (
    <div className="card stack task">
      <ItemView taskType={task.task_type} payload={task.item.payload} />
      <div className="options">
        {task.label_options.map((option, i) => (
          <button key={option} type="button" disabled={disabled} onClick={() => pick(option)}>
            {i < SHORTCUT_KEYS.length && <kbd>{SHORTCUT_KEYS[i]}</kbd>} {option}
          </button>
        ))}
      </div>
    </div>
  )
}
