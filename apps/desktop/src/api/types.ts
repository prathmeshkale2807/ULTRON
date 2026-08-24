// Shared Frontend Types mirroring backend schemas

export type SafetyMode = 'safe' | 'balanced' | 'trusted' | 'custom';

export interface ProfileState {
  mode: SafetyMode;
  updated_at: string;
  updated_by: string;
}

export interface EmergencyState {
  engaged: boolean;
  reason: string | null;
  activated_at: string | null;
  activated_by: string | null;
}

export interface HealthResponse {
  service: string;
  version: string;
  timestamp: string;
  components: {
    name: string;
    status: 'ok' | 'unavailable' | 'not_implemented';
    detail?: string;
  }[];
}

export interface TaskSummary {
  task_id: string;
  action: string;
  state: 'QUEUED' | 'PLANNING' | 'RUNNING' | 'WAITING_FOR_CONFIRMATION' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'NEEDS_RECONCILIATION';
  created_at: string;
  updated_at: string;
  error?: string;
}

export interface DeviceInfo {
  device_id: string;
  display_name: string;
  owner_id: string;
  status: 'PAIRED' | 'DISCONNECTED' | 'ONLINE';
  last_heartbeat: string | null;
  capabilities: string[];
}
