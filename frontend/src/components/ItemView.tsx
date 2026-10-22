import type { TaskType } from '../types'

/** Shows an item's content the way its task type needs. */
export default function ItemView({
  taskType,
  payload,
  size = 'large',
}: {
  taskType: TaskType
  payload: Record<string, string>
  size?: 'large' | 'thumb'
}) {
  if (taskType === 'image_classification') {
    return <img className={`item-image ${size}`} src={payload.image_url} alt="Item to label" />
  }
  return (
    <div className={`pairwise ${size}`}>
      <p className="prompt">{payload.prompt}</p>
      <div className="responses">
        <section>
          <h3>Response A</h3>
          <p>{payload.response_a}</p>
        </section>
        <section>
          <h3>Response B</h3>
          <p>{payload.response_b}</p>
        </section>
      </div>
    </div>
  )
}
