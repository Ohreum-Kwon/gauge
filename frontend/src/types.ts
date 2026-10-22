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
