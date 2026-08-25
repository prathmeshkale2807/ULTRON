import { invoke } from '@tauri-apps/api/core';

const BACKEND_URL = 'http://127.0.0.1:8756';

// Module-level variable to hold the token securely in memory.
// It is never persisted to localStorage or sessionStorage.
let _authToken: string | null = null;

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`API Error ${status}: ${detail}`);
  }
}

/**
 * Initializes the API client by fetching the secure token via a Tauri Rust command.
 */
export async function initializeApiClient(): Promise<void> {
  if (_authToken) return;
  try {
    try {
      const token = await invoke<string>('get_local_auth_token');
      if (token) {
        _authToken = token;
        console.log('API client authenticated via Tauri IPC.');
        return;
      }
    } catch {
      // In browser dev mode, fallback to dev token endpoint
      const res = await fetch(`${BACKEND_URL}/api/dev-token`);
      if (res.ok) {
        const data = await res.json();
        if (data.token) {
          _authToken = data.token;
          console.log('API client authenticated via browser dev token.');
          return;
        }
      }
    }
    throw new Error('Received empty token from backend');
  } catch (err) {
    console.error('Failed to initialize API client auth token:', err);
    throw new Error('Failed to authenticate with local backend.');
  }
}

export function clearApiClientAuthToken(): void {
  _authToken = null;
}

export function hasApiClientAuthToken(): boolean {
  return _authToken !== null;
}

/**
 * Centralized fetch wrapper that automatically attaches the auth token and normalizes errors.
 */
export async function apiClient<T>(endpoint: string, options: RequestInit & { responseType?: 'json' | 'text' | 'blob' } = {}): Promise<T> {
  const url = `${BACKEND_URL}${endpoint}`;
  
  const headers = new Headers(options.headers);
  if (!headers.has('Content-Type') && options.method && options.method !== 'GET') {
    headers.set('Content-Type', 'application/json');
  }
  
  if (_authToken) {
    headers.set('X-ULTRON-AUTH', _authToken);
  }

  let res: Response;
  try {
    res = await fetch(url, { ...options, headers });
  } catch (err) {
    throw new ApiError(503, 'Backend is unreachable or connection refused.');
  }

  if (!res.ok) {
    let detail = 'Unknown error';
    try {
      const errBody = await res.json();
      detail = errBody.detail || JSON.stringify(errBody);
    } catch {
      detail = await res.text();
    }
    throw new ApiError(res.status, detail);
  }

  const { responseType = 'json' } = options;
  if (responseType === 'blob') {
    return (await res.blob()) as unknown as T;
  }
  
  const text = await res.text();
  if (!text) return {} as T;

  if (responseType === 'text') {
    return text as unknown as T;
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    return text as unknown as T;
  }
}
