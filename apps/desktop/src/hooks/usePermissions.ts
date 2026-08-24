import { useState, useCallback } from 'react';
import { apiClient } from '../api/client';
import { usePolling } from './usePolling';
import { ProfileState, SafetyMode } from '../api/types';

export function usePermissions() {
  const [profile, setProfile] = useState<ProfileState | null>(null);

  const fetchProfile = useCallback(async () => {
    try {
      const data = await apiClient<ProfileState>('/api/profile');
      setProfile(data);
    } catch (err) {
      console.error('Failed to fetch profile', err);
    }
  }, []);

  usePolling(fetchProfile, 5000, true);

  const setSafetyMode = async (mode: SafetyMode) => {
    try {
      await apiClient('/api/profile', {
        method: 'POST',
        body: JSON.stringify({ mode })
      });
      await fetchProfile();
    } catch (err) {
      console.error('Failed to set safety mode', err);
    }
  };

  return { profile, setSafetyMode };
}
