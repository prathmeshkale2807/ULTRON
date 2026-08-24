import React from 'react';
import { NavLink } from 'react-router-dom';
import { MessageSquare, Shield, Smartphone, Activity } from 'lucide-react';

export function Sidebar() {
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
    </aside>
  );
}
