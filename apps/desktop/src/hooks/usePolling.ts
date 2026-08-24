import { useEffect, useRef, useCallback } from 'react';

/**
 * Reusable polling hook that cleans up on unmount and avoids duplicate intervals.
 * 
 * @param callback The async function to execute.
 * @param intervalMs The polling interval in milliseconds.
 * @param enabled Whether polling is currently active.
 */
export function usePolling(callback: () => Promise<void>, intervalMs: number, enabled: boolean = true) {
  const savedCallback = useRef(callback);
  const isPolling = useRef(false);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;

    let timeoutId: ReturnType<typeof setTimeout>;
    let cancelled = false;

    const tick = async () => {
      if (cancelled || isPolling.current) return;
      
      isPolling.current = true;
      try {
        await savedCallback.current();
      } catch (err) {
        console.warn('Polling error (will retry next tick):', err);
      } finally {
        isPolling.current = false;
        if (!cancelled) {
          timeoutId = setTimeout(tick, intervalMs);
        }
      }
    };

    tick();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, [intervalMs, enabled]);
}
