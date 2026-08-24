import { useState, useCallback } from 'react';
import { apiClient } from '../api/client';
import { usePolling } from './usePolling';
import { DeviceInfo } from '../api/types';

export function useDevices() {
  const [devices, setDevices] = useState<DeviceInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchDevices = useCallback(async () => {
    try {
      const data = await apiClient<{devices: DeviceInfo[]}>('/api/devices');
      setDevices(data.devices || []);
    } catch (err) {
      console.error('Failed to fetch devices', err);
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchDevices, 5000, true);

  return { devices, loading };
}
