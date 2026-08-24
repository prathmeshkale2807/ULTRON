import React from 'react';
import { useTasks } from '../hooks/useTasks';

export function TasksView() {
  const { tasks, loading, cancelTask } = useTasks();

  if (loading) return <div>Loading...</div>;

  return (
    <div>
      <h1>Tasks & Automations</h1>
      <div className="card">
        <h2>Active & Recent Tasks</h2>
        {tasks.length === 0 ? (
          <p className="subtitle">No recent tasks.</p>
        ) : (
          <ul className="component-list">
            {tasks.map(t => (
              <li key={t.task_id} className="component items-center">
                <div>
                  <div className="component-name">{t.action}</div>
                  <div className="component-detail">{t.task_id}</div>
                </div>
                <div className="flex items-center gap-4">
                  <span className={`badge badge-${t.state === 'FAILED' ? 'error' : t.state === 'COMPLETED' ? 'ok' : t.state === 'NEEDS_RECONCILIATION' ? 'error' : 'neutral'}`}>
                    {t.state}
                  </span>
                  {(t.state === 'QUEUED' || t.state === 'RUNNING' || t.state === 'WAITING_FOR_CONFIRMATION' || t.state === 'PLANNING') && (
                    <button className="btn btn-outline" style={{ padding: '0.25rem 0.5rem', fontSize: '0.8rem' }} onClick={() => cancelTask(t.task_id)}>
                      Cancel
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
