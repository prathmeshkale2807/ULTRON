import React from 'react';
import { useSafety } from '../contexts/SafetyContext';
import { usePermissions } from '../hooks/usePermissions';
import { SafetyMode } from '../api/types';

export function SecurityView() {
  const { uiState, engageEmergencyStop, resetEmergencyStop } = useSafety();
  const { profile, setSafetyMode } = usePermissions();

  const modes: SafetyMode[] = ['safe', 'balanced', 'trusted', 'custom'];

  return (
    <div>
      <h1>Security & Control Center</h1>
      
      <div className="card">
        <h2>Safety Mode Profile</h2>
        <div className="flex gap-4 mt-4">
          {modes.map(mode => (
            <button 
              key={mode}
              className={`btn ${profile?.mode === mode ? '' : 'btn-outline'}`}
              onClick={() => setSafetyMode(mode)}
              style={{ textTransform: 'capitalize' }}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      <div className="card" style={{ border: '1px solid #7f1d1d' }}>
        <h2 className="text-error">Emergency Stop</h2>
        <p className="subtitle" style={{ marginBottom: '1rem' }}>
          Instantly halts all automated tasks, clears the background queue, and disables execution capabilities.
        </p>
        
        <div className="flex gap-4">
          <button 
            className="btn btn-danger" 
            onClick={engageEmergencyStop}
            disabled={uiState === 'ENGAGED' || uiState === 'REQUESTING'}
          >
            Engage Emergency Stop
          </button>
          
          <button 
            className="btn btn-outline" 
            onClick={resetEmergencyStop}
            disabled={uiState === 'READY' || uiState === 'RESETTING'}
          >
            Reset System
          </button>
        </div>
        
        <div className="mt-4">
          Status: <span className={`badge badge-${uiState === 'ENGAGED' ? 'error' : uiState === 'READY' ? 'ok' : 'warning'}`}>{uiState}</span>
        </div>
      </div>
    </div>
  );
}
