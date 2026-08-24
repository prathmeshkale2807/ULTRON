import { useState, useCallback } from 'react';
import { apiClient } from '../api/client';
import { usePolling } from './usePolling';
import { TaskSummary } from '../api/types';

export function useTasks() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTasks = useCallback(async () => {
    try {
      const data = await apiClient<TaskSummary[]>('/api/tasks');
      setTasks(data);
    } catch (err) {
      console.error('Failed to fetch tasks', err);
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchTasks, 3000, true);

  const cancelTask = async (taskId: string) => {
    try {
      await apiClient(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
      await fetchTasks();
    } catch (err) {
      console.error('Failed to cancel task', err);
    }
  };

  return { tasks, loading, cancelTask };
}
