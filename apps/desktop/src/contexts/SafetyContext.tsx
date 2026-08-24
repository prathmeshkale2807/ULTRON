import React, { createContext, useContext, useState, useCallback } from 'react';
import { apiClient } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { EmergencyState } from '../api/types';

export type EmergencyUIState = 'REQUESTING' | 'ENGAGED' | 'RESETTING' | 'READY';

interface SafetyContextValue {
  uiState: EmergencyUIState;
  backendState: EmergencyState | null;
  engageEmergencyStop: () => Promise<void>;
  resetEmergencyStop: () => Promise<void>;
}

const SafetyContext = createContext<SafetyContextValue | undefined>(undefined);

export function SafetyProvider({ children }: { children: React.ReactNode }) {
  const [uiState, setUiState] = useState<EmergencyUIState>('READY');
  const [backendState, setBackendState] = useState<EmergencyState | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const state = await apiClient<EmergencyState>('/api/emergency/status');
      setBackendState(state);
      
      // Sync UI state based on verified backend state if we aren't in a transitional state
      setUiState((prev) => {
        if (state.engaged) {
          return prev === 'RESETTING' ? prev : 'ENGAGED';
        } else {
          return prev === 'REQUESTING' ? prev : 'READY';
        }
      });
    } catch (e) {
      console.error("Failed to fetch emergency status", e);
    }
  }, []);

  // Poll status every 2.5 seconds
  usePolling(fetchStatus, 2500, true);

  const engageEmergencyStop = async () => {
    setUiState('REQUESTING');
    try {
      await apiClient('/api/emergency/activate', {
        method: 'POST',
        body: JSON.stringify({ reason: 'User initiated emergency stop via UI' })
      });
      await fetchStatus();
    } catch (err) {
      console.error('Failed to engage emergency stop', err);
      setUiState('READY');
    }
  };

  const resetEmergencyStop = async () => {
    setUiState('RESETTING');
    try {
      await apiClient('/api/emergency/reset', { method: 'POST', body: '{}' });
      await fetchStatus();
    } catch (err) {
      console.error('Failed to reset emergency stop', err);
      setUiState('ENGAGED');
    }
  };

  return (
    <SafetyContext.Provider value={{ uiState, backendState, engageEmergencyStop, resetEmergencyStop }}>
      {children}
    </SafetyContext.Provider>
  );
}

export function useSafety() {
  const ctx = useContext(SafetyContext);
  if (!ctx) throw new Error('useSafety must be used within SafetyProvider');
  return ctx;
}
