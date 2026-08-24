import React from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { useAuth } from '../contexts/AuthContext';
import { useSafety } from '../contexts/SafetyContext';
import { AlertTriangle } from 'lucide-react';

export function MainLayout() {
  const { backendState, errorDetail } = useAuth();
  const { uiState } = useSafety();

  if (backendState !== 'READY') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', width: '100vw' }}>
        <h1>ULTRON Backend: {backendState}</h1>
        {errorDetail && <p className="text-error">{errorDetail}</p>}
      </div>
    );
  }

  return (
    <div className="app-container">
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {(uiState === 'ENGAGED' || uiState === 'REQUESTING' || uiState === 'RESETTING') && (
          <div className="emergency-banner flex items-center justify-center gap-2">
            <AlertTriangle size={18} />
            EMERGENCY STOP {uiState}
          </div>
        )}
        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
