import { useEffect, useState } from "react";

// Phase 1 scope: this UI proves the desktop shell can actually reach the
// backend over HTTP and render its real response. There is no chat UI,
// no device dashboard, no voice indicator yet -- those are later phases,
// and this file will grow into the real Status/Conversation/Devices
// panels described in the architecture doc rather than being thrown away.

const BACKEND_URL = "http://127.0.0.1:8756";

interface ComponentStatus {
  name: string;
  status: "ok" | "unavailable" | "not_implemented";
  detail?: string;
}

interface HealthResponse {
  service: string;
  version: string;
  timestamp: string;
  components: ComponentStatus[];
}

type ConnectionState = "connecting" | "connected" | "unreachable";

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function pollHealth() {
      try {
        const res = await fetch(`${BACKEND_URL}/api/health`);
        if (!res.ok) throw new Error(`Backend returned HTTP ${res.status}`);
        const data: HealthResponse = await res.json();
        if (!cancelled) {
          setHealth(data);
          setConnection("connected");
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setConnection("unreachable");
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }

    pollHealth();
    const interval = setInterval(pollHealth, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <main className="app">
      <h1>ULTRON</h1>
      <p className="subtitle">Phase 1 — infrastructure scaffold</p>

      <section className="status-card">
        <h2>Backend connection</h2>
        <p className={`badge badge-${connection}`}>{connection}</p>
        {error && <p className="error">Could not reach backend: {error}</p>}
      </section>

      {health && (
        <section className="status-card">
          <h2>{health.service}</h2>
          <p className="version">v{health.version}</p>
          <ul className="component-list">
            {health.components.map((c) => (
              <li key={c.name} className={`component component-${c.status}`}>
                <span className="component-name">{c.name}</span>
                <span className="component-status">{c.status}</span>
                {c.detail && <span className="component-detail">{c.detail}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
