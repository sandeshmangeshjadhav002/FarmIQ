/**
 * useApi — tiny data-fetching hook that calls an API endpoint on mount.
 *
 * Usage:
 *   const { data, loading, error, refetch } = useApi("/api/farms");
 *
 * Returns { data, loading, error, refetch }.
 * `data` is the raw parsed JSON from the endpoint.
 * Re-fetches when `url` or any item in `deps` changes.
 */
import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/apiClient";

export default function useApi(url, deps = []) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  const fetch_ = useCallback(async () => {
    if (!url) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiGet(url);
      setData(res);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps]);

  useEffect(() => { fetch_(); }, [fetch_]);

  return { data, loading, error, refetch: fetch_ };
}
