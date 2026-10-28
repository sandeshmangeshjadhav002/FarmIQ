/**
 * useApi — tiny data-fetching hook that calls an API endpoint on mount.
 *
 * Usage:
 *   const { data, loading, error, refetch } = useApi("/api/farms");
 *
 * Returns { data, loading, error, refetch }.
 * `data` is the raw parsed JSON from the endpoint.
 * Re-fetches when `url` or any item in `deps` changes.
 * Passing a falsy `url` disables fetching and reports `loading: false`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/apiClient";

export default function useApi(url, deps = []) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  // Monotonic request id. When `url`/`deps` change quickly — or in React
  // StrictMode, where every effect runs twice — a slower earlier response
  // could otherwise land after a newer one and leave the screen showing
  // stale data. Only the newest request is allowed to touch state.
  const latestRequest = useRef(0);

  const fetch_ = useCallback(async () => {
    const id = ++latestRequest.current;

    if (!url) {
      // Nothing to fetch (a conditionally-disabled call site): a permanent
      // spinner would be wrong, so settle straight away.
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await apiGet(url);
      if (id === latestRequest.current) setData(res);
    } catch (err) {
      if (id === latestRequest.current) setError(err);
    } finally {
      if (id === latestRequest.current) setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps]);

  useEffect(() => { fetch_(); }, [fetch_]);

  return { data, loading, error, refetch: fetch_ };
}
