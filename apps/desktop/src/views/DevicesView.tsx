import React from 'react';
import { useDevices } from '../hooks/useDevices';

export function DevicesView() {
  const { devices, loading } = useDevices();

  if (loading) return <div>Loading...</div>;

  return (
    <div>
      <h1>Devices</h1>
      <div className="card">
        <h2>Paired Android Devices</h2>
        {devices.length === 0 ? (
          <p className="subtitle">No devices paired yet.</p>
        ) : (
          <ul className="component-list">
            {devices.map(d => (
              <li key={d.device_id} className="component items-center">
                <div>
                  <div className="component-name">{d.display_name}</div>
                  <div className="component-detail">ID: {d.device_id.slice(0, 8)}...</div>
                </div>
                <div className="flex items-center gap-4">
                  <span className={`badge badge-${d.status === 'ONLINE' ? 'ok' : 'neutral'}`}>
                    {d.status}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
