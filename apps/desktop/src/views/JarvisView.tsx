import React, { useState, useEffect, useRef } from 'react';
import { OrbCore, OrbState } from '../components/OrbCore';
import { apiClient } from '../api/client';
import { useSafety } from '../contexts/SafetyContext';
import {
  Mic,
  MicOff,
  Cpu,
  Monitor,
  Smartphone,
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  Play,
  Volume2,
  FileText,
  Globe,
  Camera,
  Battery,
  Search,
  CheckCircle,
  XCircle,
  Radio,
  Activity,
} from 'lucide-react';

interface VoiceStatus {
  status: string;
  stt_configured: boolean;
  tts_configured: boolean;
  wake_word: string;
  microphone_available: boolean;
  microphone_name: string | null;
  speaker_available: boolean;
  speaker_name: string | null;
  active_session: {
    state: string;
    active_conversation: boolean;
    conversation_id: string | null;
  } | null;
}

interface ActivityEvent {
  id: string;
  timestamp: string;
  type: 'state' | 'transcript' | 'response' | 'tool' | 'error' | 'confirmation';
  text: string;
}

export function JarvisView() {
  const [voiceState, setVoiceState] = useState<OrbState>('STANDBY');
  const [transcript, setTranscript] = useState<string>('');
  const [lastResponse, setLastResponse] = useState<string>('');
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [activityLog, setActivityLog] = useState<ActivityEvent[]>([]);
  const [deviceCount, setDeviceCount] = useState<number>(0);
  const [phoneBattery, setPhoneBattery] = useState<number | null>(null);
  const [pendingConfirmations, setPendingConfirmations] = useState<any[]>([]);
  const [isPttActive, setIsPttActive] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const { uiState, engageEmergencyStop } = useSafety();

  const addEvent = (type: ActivityEvent['type'], text: string) => {
    const timeStr = new Date().toLocaleTimeString();
    setActivityLog((prev) => [
      ...prev.slice(-30),
      { id: `${Date.now()}-${Math.random()}`, timestamp: timeStr, type, text },
    ]);
  };

  // 1. Initial status fetch & device count
  useEffect(() => {
    apiClient<VoiceStatus>('/api/voice/status')
      .then((res) => {
        setVoiceStatus(res);
        if (res.active_session?.state) {
          setVoiceState(res.active_session.state as OrbState);
        }
      })
      .catch(() => {});

    apiClient<any[]>('/api/devices')
      .then((devices) => {
        const connected = devices.filter((d) => d.status === 'CONNECTED' || d.status === 'ACTIVE');
        setDeviceCount(connected.length);
      })
      .catch(() => {});

    addEvent('state', 'ULTRON Neural Core Initialized');
  }, []);

  // 2. Real-time Event Stream / Polling
  useEffect(() => {
    let isMounted = true;
    const interval = setInterval(async () => {
      if (!isMounted) return;
      try {
        const status = await apiClient<VoiceStatus>('/api/voice/status');
        setVoiceStatus(status);
        if (status.active_session?.state) {
          const nextState = status.active_session.state as OrbState;
          setVoiceState((prev) => {
            if (prev !== nextState) {
              addEvent('state', `State transition: ${nextState}`);
            }
            return nextState;
          });
        }

        // Check pending confirmations
        const confs = await apiClient<any[]>('/api/confirmations/pending');
        setPendingConfirmations(confs || []);
      } catch (e) {}
    }, 1000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Auto-scroll activity log
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activityLog]);

  // Push to talk handler
  const handlePushToTalk = async () => {
    setIsPttActive(true);
    try {
      await apiClient('/api/voice/push-to-talk', { method: 'POST' });
      setVoiceState('LISTENING');
      addEvent('transcript', 'Push-to-talk triggered');
    } catch (e) {
      addEvent('error', 'Push-to-talk failed to trigger');
    } finally {
      setIsPttActive(false);
    }
  };

  // Quick Action execution through backend conversation API
  const handleQuickCommand = async (commandText: string) => {
    addEvent('transcript', `Quick Command: "${commandText}"`);
    setVoiceState('PROCESSING');
    setTranscript(commandText);
    try {
      const convs = await apiClient<any>('/api/conversations/active', {
        method: 'POST',
      }).catch(() => null);
      const convId = convs?.id || 'conv-jarvis-hud';

      const res = await apiClient<any>(`/api/conversations/${convId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content: commandText }),
      });

      if (res?.content) {
        setLastResponse(res.content);
        addEvent('response', res.content);
      }
    } catch (e: any) {
      addEvent('error', `Command failed: ${e?.message || 'Error executing'}`);
    } finally {
      setVoiceState('STANDBY');
    }
  };

  const handleResolveConfirmation = async (id: string, approved: boolean) => {
    try {
      await apiClient(`/api/confirmations/${id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ approved, reason: approved ? 'Approved by User via HUD' : 'Cancelled by User via HUD' }),
      });
      setPendingConfirmations((prev) => prev.filter((c) => c.id !== id));
      addEvent('confirmation', `Confirmation ${id} ${approved ? 'APPROVED' : 'REJECTED'}`);
    } catch (e) {
      addEvent('error', 'Failed to resolve confirmation');
    }
  };

  const getStateBadgeStyle = () => {
    switch (voiceState) {
      case 'LISTENING':
        return { color: '#00ffaa', border: '1px solid #00ffaa', background: 'rgba(0, 255, 170, 0.15)' };
      case 'SPEAKING':
        return { color: '#00c3ff', border: '1px solid #00c3ff', background: 'rgba(0, 195, 255, 0.15)' };
      case 'PROCESSING':
      case 'THINKING':
        return { color: '#aa50ff', border: '1px solid #aa50ff', background: 'rgba(170, 80, 255, 0.15)' };
      case 'EXECUTING':
        return { color: '#ff8c00', border: '1px solid #ff8c00', background: 'rgba(255, 140, 0, 0.15)' };
      case 'WAITING_FOR_CONFIRMATION':
        return { color: '#ffcc00', border: '1px solid #ffcc00', background: 'rgba(255, 204, 0, 0.2)' };
      case 'ERROR':
        return { color: '#ff4444', border: '1px solid #ff4444', background: 'rgba(255, 68, 68, 0.2)' };
      default:
        return { color: '#00d2ff', border: '1px solid #00d2ff', background: 'rgba(0, 210, 255, 0.1)' };
    }
  };

  return (
    <div className="jarvis-container">
      {/* ── TOP HOLOGRAPHIC STATUS BAR ────────────────────────────────────── */}
      <header className="jarvis-header">
        <div className="jarvis-brand">
          <div className="brand-dot" />
          <span className="brand-name">ULTRON</span>
          <span className="brand-subtitle">// NEURAL CORE v4.0</span>
        </div>

        <div className="jarvis-status-ribbon">
          <div className="status-pill status-pill-online">
            <Cpu size={14} />
            <span>AI CORE</span>
            <div className="led led-green" />
          </div>

          <div className="status-pill status-pill-online">
            <Radio size={14} />
            <span>VOICE: {voiceStatus?.microphone_available ? 'READY' : 'OFFLINE'}</span>
            <div className={`led ${voiceStatus?.microphone_available ? 'led-green' : 'led-red'}`} />
          </div>

          <div className="status-pill status-pill-online">
            <Monitor size={14} />
            <span>PC TOOLS: READY</span>
            <div className="led led-green" />
          </div>

          <div className="status-pill status-pill-online">
            <Smartphone size={14} />
            <span>ANDROID: {deviceCount > 0 ? `${deviceCount} CONNECTED` : 'STANDBY'}</span>
            <div className={`led ${deviceCount > 0 ? 'led-green' : 'led-amber'}`} />
          </div>

          <div className="status-pill status-pill-online">
            <ShieldCheck size={14} />
            <span>SAFETY GATE: ARMED</span>
            <div className="led led-green" />
          </div>
        </div>
      </header>

      {/* ── MAIN HUD STAGE ──────────────────────────────────────────────── */}
      <div className="jarvis-body">
        {/* Left Side: System Activity Log */}
        <section className="jarvis-panel jarvis-panel-left">
          <div className="panel-title">
            <Activity size={16} />
            <span>NEURAL ACTIVITY FEED</span>
          </div>

          <div className="activity-feed-scroll">
            {activityLog.length === 0 ? (
              <div className="empty-feed">System telemetry online. Awaiting input.</div>
            ) : (
              activityLog.map((ev) => (
                <div key={ev.id} className={`activity-row activity-${ev.type}`}>
                  <span className="activity-time">[{ev.timestamp}]</span>
                  <span className="activity-text">{ev.text}</span>
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </section>

        {/* Center: 3D Holographic Core & Real-Time Interaction */}
        <section className="jarvis-center-stage">
          <div className="orb-wrapper">
            <OrbCore state={voiceState} size={300} interactive onClick={handlePushToTalk} />

            {/* State HUD Badge */}
            <div className="state-badge-container">
              <div className="state-badge" style={getStateBadgeStyle()}>
                <span className="state-bracket">[</span>
                <span className="state-text">{voiceState}</span>
                <span className="state-bracket">]</span>
              </div>
            </div>

            {/* Frequency Bar Visualizer */}
            <div className="frequency-visualizer">
              {Array.from({ length: 20 }).map((_, i) => {
                const isActive = voiceState === 'SPEAKING' || voiceState === 'LISTENING';
                const height = isActive ? Math.max(4, Math.sin(i * 0.5 + Date.now() * 0.005) * 18 + 12) : 3;
                return (
                  <div
                    key={i}
                    className="freq-bar"
                    style={{
                      height: `${height}px`,
                      background: voiceState === 'SPEAKING' ? '#00c3ff' : '#00ffaa',
                    }}
                  />
                );
              })}
            </div>
          </div>

          {/* Subtitles & Spoken Dialogue Box */}
          <div className="dialogue-box">
            {transcript && (
              <div className="dialogue-spoken">
                <span className="dialogue-label">USER:</span>
                <span className="dialogue-text">"{transcript}"</span>
              </div>
            )}
            {lastResponse && (
              <div className="dialogue-ultron">
                <span className="dialogue-label">ULTRON:</span>
                <span className="dialogue-text">"{lastResponse}"</span>
              </div>
            )}
            {!transcript && !lastResponse && (
              <div className="dialogue-idle">
                Say <strong>"Hey ULTRON"</strong> or directly speak a command like <strong>"Open Chrome"</strong>
              </div>
            )}
          </div>

          {/* Push To Talk / Mic Action */}
          <div className="center-controls">
            <button
              className={`ptt-button ${isPttActive || voiceState === 'LISTENING' ? 'ptt-active' : ''}`}
              onClick={handlePushToTalk}
            >
              <Mic size={18} />
              <span>{voiceState === 'LISTENING' ? 'MICROPHONE ACTIVE' : 'PUSH TO TALK'}</span>
            </button>
          </div>
        </section>

        {/* Right Side: Quick Holographic Directives */}
        <section className="jarvis-panel jarvis-panel-right">
          <div className="panel-title">
            <Monitor size={16} />
            <span>QUICK DIRECTIVES</span>
          </div>

          <div className="quick-actions-grid">
            <button className="quick-btn" onClick={() => handleQuickCommand('Open Chrome')}>
              <Globe size={18} className="btn-icon" />
              <div className="btn-details">
                <span className="btn-title">Open Chrome</span>
                <span className="btn-sub">Browser Automation</span>
              </div>
            </button>

            <button className="quick-btn" onClick={() => handleQuickCommand('Open Notepad')}>
              <FileText size={18} className="btn-icon" />
              <div className="btn-details">
                <span className="btn-title">Open Notepad</span>
                <span className="btn-sub">Desktop PC Control</span>
              </div>
            </button>

            <button className="quick-btn" onClick={() => handleQuickCommand('Take screenshot')}>
              <Camera size={18} className="btn-icon" />
              <div className="btn-details">
                <span className="btn-title">Take Screenshot</span>
                <span className="btn-sub">Display Capture</span>
              </div>
            </button>

            <button className="quick-btn" onClick={() => handleQuickCommand('Search YouTube for Iron Man')}>
              <Search size={18} className="btn-icon" />
              <div className="btn-details">
                <span className="btn-title">Search YouTube</span>
                <span className="btn-sub">Web Action</span>
              </div>
            </button>

            <button className="quick-btn" onClick={() => handleQuickCommand("What's my phone battery?")}>
              <Battery size={18} className="btn-icon" />
              <div className="btn-details">
                <span className="btn-title">Phone Battery</span>
                <span className="btn-sub">Android Companion</span>
              </div>
            </button>

            <button
              className="quick-btn quick-btn-danger"
              onClick={() => {
                engageEmergencyStop();
                addEvent('error', 'EMERGENCY STOP TRIGGERED VIA HUD');
              }}
            >
              <AlertTriangle size={18} className="btn-icon text-red" />
              <div className="btn-details">
                <span className="btn-title">EMERGENCY STOP</span>
                <span className="btn-sub">Kill All Tasks</span>
              </div>
            </button>
          </div>
        </section>
      </div>

      {/* ── SAFETY CONFIRMATION MODAL (CONFIRMATION BROKER) ───────────────── */}
      {pendingConfirmations.length > 0 && (
        <div className="confirmation-overlay">
          <div className="confirmation-modal">
            <div className="modal-header">
              <ShieldAlert size={24} className="text-amber" />
              <h2>SAFETY CONFIRMATION REQUIRED</h2>
            </div>
            {pendingConfirmations.map((conf) => (
              <div key={conf.id} className="confirmation-card">
                <div className="conf-field">
                  <span className="conf-label">OPERATION:</span>
                  <span className="conf-value">{conf.tool_name || 'Restricted Action'}</span>
                </div>
                <div className="conf-field">
                  <span className="conf-label">TARGET DEVICE:</span>
                  <span className="conf-value">{conf.target_device || 'Local System'}</span>
                </div>
                <div className="conf-field">
                  <span className="conf-label">RISK LEVEL:</span>
                  <span className="conf-value risk-high">{conf.risk_level || 'HIGH'}</span>
                </div>
                <div className="conf-details">
                  <pre>{JSON.stringify(conf.arguments || {}, null, 2)}</pre>
                </div>

                <div className="conf-actions">
                  <button className="conf-btn conf-btn-reject" onClick={() => handleResolveConfirmation(conf.id, false)}>
                    <XCircle size={18} />
                    <span>REJECT [NO]</span>
                  </button>
                  <button className="conf-btn conf-btn-accept" onClick={() => handleResolveConfirmation(conf.id, true)}>
                    <CheckCircle size={18} />
                    <span>CONFIRM [YES]</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
