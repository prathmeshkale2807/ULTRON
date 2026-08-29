import React, { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { MessageSquare, Shield, Smartphone, Activity, Mic, Radio } from 'lucide-react';
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
        <span style={{ color: '#00d2ff', textShadow: '0 0 10px rgba(0,210,255,0.5)' }}>ULTRON</span>
      </div>
      <nav style={{ flex: 1, marginTop: '1rem' }}>
        <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} end>
          <Radio size={18} style={{ color: '#00ffaa' }} /> JARVIS Core
        </NavLink>
        <NavLink to="/chat" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <MessageSquare size={18} /> Console / Chat
        </NavLink>
        <NavLink to="/devices" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Smartphone size={18} /> Devices & Android
        </NavLink>
        <NavLink to="/tasks" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Activity size={18} /> Tasks & Automations
        </NavLink>
        <NavLink to="/security" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Shield size={18} /> Security & Audit
        </NavLink>
      </nav>
      <div style={{ padding: '0.75rem 1rem', borderTop: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem', color: 'var(--color-text-sub)' }}>
        <Mic size={16} style={{ color: voiceStatus === 'LISTENING' ? '#3b82f6' : voiceStatus === 'SPEAKING' ? '#8b5cf6' : '#10b981' }} />
        <span>Voice: {voiceStatus}</span>
      </div>
    </aside>
  );
}
