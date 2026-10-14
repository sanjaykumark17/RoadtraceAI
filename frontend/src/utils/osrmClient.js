/**
 * Frontend OSRM Client helper.
 * Provides client-side utilities to query OSRM /route/v1/driving/ and /table/v1/driving/.
 */

const DEFAULT_OSRM_URL = import.meta.env?.VITE_OSRM_URL || "http://localhost:5000";

/**
 * Fetch road-snapped route between coordinates.
 * @param {Array<[number, number]>} coordinates - Array of [lon, lat] coordinates.
 * @param {string} [osrmUrl] - Optional base OSRM URL.
 * @returns {Promise<{coordinates: Array<[number, number]>, distanceMeters: number, durationSeconds: number} | null>}
 */
export async function fetchRoadRoute(coordinates, osrmUrl = DEFAULT_OSRM_URL) {
  if (!coordinates || coordinates.length < 2) return null;

  const coordStr = coordinates.map((c) => `${c[0]},${c[1]}`).join(";");
  const base = osrmUrl.replace(/\/+$/, "");
  const url = `${base}/route/v1/driving/${coordStr}?overview=full&geometries=geojson`;

  try {
    const res = await fetch(url, {
      method: "GET",
      signal: AbortSignal.timeout(3000),
    });

    if (!res.ok) return null;

    const data = await res.json();
    if (data.code === "Ok" && data.routes && data.routes.length > 0) {
      const primary = data.routes[0];
      return {
        coordinates: primary.geometry.coordinates,
        distanceMeters: primary.distance,
        durationSeconds: primary.duration,
      };
    }
  } catch {
    // Fallback gracefully on timeout or unreachable OSRM service
    return null;
  }

  return null;
}

/**
 * Calculate distance matrix between coordinates using /table/ endpoint.
 * @param {Array<[number, number]>} coordinates - Array of [lon, lat] coordinates.
 * @param {string} [osrmUrl]
 * @returns {Promise<Array<Array<number>> | null>}
 */
export async function fetchDistanceMatrix(coordinates, osrmUrl = DEFAULT_OSRM_URL) {
  if (!coordinates || coordinates.length < 2) return null;

  const coordStr = coordinates.map((c) => `${c[0]},${c[1]}`).join(";");
  const base = osrmUrl.replace(/\/+$/, "");
  const url = `${base}/table/v1/driving/${coordStr}?annotations=distance`;

  try {
    const res = await fetch(url, {
      method: "GET",
      signal: AbortSignal.timeout(3000),
    });

    if (!res.ok) return null;

    const data = await res.json();
    if (data.code === "Ok" && data.distances) {
      return data.distances;
    }
  } catch {
    return null;
  }

  return null;
}

export default {
  fetchRoadRoute,
  fetchDistanceMatrix,
};
