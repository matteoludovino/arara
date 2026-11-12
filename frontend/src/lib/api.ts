/** Every call goes to /api on this origin, with the session cookie and Django's CSRF token. */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    /** The domain error code (`insufficient_stock`, `discount_needs_approval`…), when there is one. */
    readonly code: string | undefined,
    /** The whole body: some errors carry details (`shortages`, `percent`…). */
    readonly data: Record<string, unknown>,
  ) {
    super(message);
  }
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

const CSRF_COOKIES = ['__Host-csrftoken', 'csrftoken'];

function csrfToken(): string | undefined {
  for (const pair of document.cookie.split('; ')) {
    const [name, value] = pair.split('=');
    if (name && value && CSRF_COOKIES.includes(name)) return decodeURIComponent(value);
  }
  return undefined;
}

/** DRF validation errors nest by field and by list index: flatten them to sentences. */
export function errorMessages(body: unknown): string[] {
  if (typeof body === 'string') return [body];
  if (Array.isArray(body)) return body.flatMap(errorMessages);
  if (body && typeof body === 'object') {
    return Object.entries(body).flatMap(([key, value]) => (key === 'code' ? [] : errorMessages(value)));
  }
  return [];
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') {
    if (!csrfToken()) await fetch('/api/auth/csrf', { credentials: 'same-origin' });
    headers['X-CSRFToken'] = csrfToken() ?? '';
  }
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // A domain error says it in `detail`; its other keys are data (shortages, percent…), not text.
    const messages = typeof data.detail === 'string' ? [data.detail] : [...new Set(errorMessages(data))];
    const message = messages.length ? messages.slice(0, 3).join(' ') : 'Algo deu errado. Tente de novo.';
    throw new ApiError(res.status, message, typeof data.code === 'string' ? data.code : undefined, data);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body: unknown = {}) => request<T>('POST', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  delete: <T>(path: string) => request<T>('DELETE', path),
};

export const qs = (params: Record<string, string | number | boolean | null | undefined>) => {
  const entries = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => [k, String(v)]);
  return entries.length ? `?${new URLSearchParams(entries)}` : '';
};
