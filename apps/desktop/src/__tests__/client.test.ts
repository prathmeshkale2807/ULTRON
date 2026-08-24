import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiClient, initializeApiClient, ApiError, clearApiClientAuthToken, hasApiClientAuthToken } from '../api/client';

// Mock Tauri invoke
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(async (cmd) => {
    if (cmd === 'get_local_auth_token') return 'mock-token';
    return null;
  })
}));

describe('API Client', () => {
  beforeEach(() => {
    clearApiClientAuthToken();
    vi.stubGlobal('fetch', vi.fn());
  });

  it('initializes auth token via tauri', async () => {
    expect(hasApiClientAuthToken()).toBe(false);
    await initializeApiClient();
    expect(hasApiClientAuthToken()).toBe(true);
  });

  it('attaches auth token to requests after initialization', async () => {
    await initializeApiClient();
    const fetchMock = vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    
    await apiClient('/test');
    
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const headers = fetchMock.mock.calls[0][1]?.headers as Headers;
    expect(headers.get('X-ULTRON-AUTH')).toBe('mock-token');
  });

  it('throws ApiError on 401', async () => {
    await initializeApiClient();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Unauthorized' }), { status: 401 }));
    
    await expect(apiClient('/test')).rejects.toThrow(ApiError);
  });
});
