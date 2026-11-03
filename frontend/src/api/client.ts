/** Thin fetch wrapper: JSON in/out, CSRF header on writes, problem+json → ApiError. */

export const API_BASE = '/api/v1'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export interface Problem {
  status: number
  code: string
  title: string
  detail?: string
  errors?: { loc: (string | number)[]; msg: string; type: string }[]
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly problem: Problem

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title)
    this.name = 'ApiError'
    this.status = problem.status
    this.code = problem.code
    this.problem = problem
  }

  /** First field-level validation message, for showing next to a form. */
  get fieldMessage(): string | undefined {
    return this.problem.errors?.[0]?.msg
  }
}

export async function api<T>(
  path: string,
  { method = 'GET', body }: { method?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (!SAFE_METHODS.has(method)) headers['X-Finboard-Client'] = '1' // ADR-0015
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!response.ok) {
    let problem: Problem
    try {
      problem = (await response.json()) as Problem
    } catch {
      problem = { status: response.status, code: 'http_error', title: response.statusText }
    }
    throw new ApiError({ ...problem, status: response.status })
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.fieldMessage ?? error.message
  if (error instanceof Error) return error.message
  return 'Something went wrong'
}
