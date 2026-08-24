import React, { createContext, useContext, useEffect, useState } from 'react';
import { initializeApiClient } from '../api/client';

export type BackendState = 'STARTING' | 'READY' | 'MIGRATING' | 'UNAVAILABLE' | 'ERROR';

interface AuthContextValue {
  backendState: BackendState;
  errorDetail: string | null;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [backendState, setBackendState] = useState<BackendState>('STARTING');
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function checkReadiness() {
      try {
        // Poll for readiness (Wait for PyInstaller sidecar to come up)
        const res = await fetch('http://127.0.0.1:8756/api/ready');
        if (res.ok) {
          // It's ready, now initialize the API client to fetch the token
          await initializeApiClient();
          if (!cancelled) {
            setBackendState('READY');
            setErrorDetail(null);
          }
        } else {
          if (!cancelled) setBackendState('UNAVAILABLE');
        }
      } catch (err) {
        if (!cancelled) {
          setBackendState('UNAVAILABLE');
          setErrorDetail(err instanceof Error ? err.message : String(err));
        }
      }
    }

    const interval = setInterval(() => {
      if (backendState !== 'READY') {
        checkReadiness();
      }
    }, 2000);
    
    checkReadiness();

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [backendState]);

  return (
    <AuthContext.Provider value={{ backendState, errorDetail }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
