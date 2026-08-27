import React, { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { MessageSquare, Shield, Smartphone, Activity, Mic } from 'lucide-react';
import { apiClient } from '../api/client';

export function Sidebar() {
  const [voiceStatus, setVoiceStatus] = useState<string>('STANDBY');

  useEffect(() => {
    let mounted = true;
    apiClient<{ status: string; active_session?: { state: string } }>('/api/voice/status')
      .then((data) => {
        if (mounted && data) {
          setVoiceStatus(data.active_session?.state || 'STANDBY');
        }
      })
      .catch(() => {});
    return () => { mounted = false; };
  }, []);

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        ULTRON
      </div>
      <nav style={{ flex: 1, marginTop: '1rem' }}>
        <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} end>
          <MessageSquare size={18} /> Chat
        </NavLink>
        <NavLink to="/devices" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Smartphone size={18} /> Devices
        </NavLink>
        <NavLink to="/tasks" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Activity size={18} /> Tasks & Automations
        </NavLink>
        <NavLink to="/security" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Shield size={18} /> Security
        </NavLink>
      </nav>
      <div style={{ padding: '0.75rem 1rem', borderTop: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--color-text-sub)' }}>
        <Mic size={16} style={{ color: voiceStatus === 'LISTENING' ? '#3b82f6' : voiceStatus === 'SPEAKING' ? '#8b5cf6' : '#10b981' }} />
        <span>Voice: {voiceStatus}</span>
      </div>
    </aside>
  );
}
