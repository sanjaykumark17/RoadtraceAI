import { useState, useCallback, useEffect } from "react";
import apiClient from "../api/client";

/**
 * Speed threshold color assignment as per system specification:
 * - Green: < 40 km/h
 * - Amber: 40 - 80 km/h
 * - Red: > 80 km/h
 */
export function getSpeedColor(speed) {
  if (speed === null || speed === undefined || isNaN(speed)) {
    return "#10b981"; // default green
  }
  const s = Number(speed);
  if (s < 40) return "#10b981";      // green < 40
  if (s <= 80) return "#f59e0b";     // amber 40 - 80
  return "#ef4444";                  // red > 80
}

export function getSpeedCategory(speed) {
  if (speed === null || speed === undefined || isNaN(speed)) return "low";
  const s = Number(speed);
  if (s < 40) return "low";
  if (s <= 80) return "medium";
  return "high";
}

export function haversineDistanceKm(lat1, lon1, lat2, lon2) {
  const R = 6371.0;
  const dLat = ((lat2 - lat1) * Math.PI) / 180.0;
  const dLon = ((lon2 - lon1) * Math.PI) / 180.0;
  const a =
    Math.sin(dLat / 2.0) * Math.sin(dLat / 2.0) +
    Math.cos((lat1 * Math.PI) / 180.0) *
      Math.cos((lat2 * Math.PI) / 180.0) *
      Math.sin(dLon / 2.0) *
      Math.sin(dLon / 2.0);
  const c = 2.0 * Math.atan2(Math.sqrt(a), Math.sqrt(1.0 - a));
  return R * c;
}

export function parseTrajectoryData(rawGeoJson) {
  if (!rawGeoJson || !rawGeoJson.features) {
    return {
      plate: "",
      points: [],
      segments: [],
      totalSightings: 0,
    };
  }

  const pointFeatures = rawGeoJson.features.filter(
    (f) => f.geometry && f.geometry.type === "Point"
  );
  const lineFeature = rawGeoJson.features.find(
    (f) => f.geometry && f.geometry.type === "LineString"
  );

  const rawSpeeds =
    lineFeature?.properties?.segment_speeds ||
    lineFeature?.properties?.speeds ||
    [];

  // Sort point features chronologically by timestamp
  const sortedPoints = [...pointFeatures].sort((a, b) => {
    const tA = new Date(a.properties.timestamp).getTime();
    const tB = new Date(b.properties.timestamp).getTime();
    return tA - tB;
  });

  const points = sortedPoints.map((feat, idx) => {
    const coords = feat.geometry.coordinates; // [lon, lat]
    const props = feat.properties || {};
    const lat = props.latitude !== undefined ? Number(props.latitude) : Number(coords[1]);
    const lng = props.longitude !== undefined ? Number(props.longitude) : Number(coords[0]);

    return {
      id: props.id || `point-${idx}`,
      markerIndex: idx + 1,
      lat,
      lng,
      cameraName: props.camera_name || props.camera || `Camera #${idx + 1}`,
      timestamp: props.timestamp,
      dwellSeconds: props.dwell_seconds,
      ocrConfidence: props.ocr_confidence,
      snapshotUrl: props.snapshot_url,
      plate: props.plate || props.plate_number || rawGeoJson.plate,
      estimatedSpeed: idx > 0 ? rawSpeeds[idx - 1] ?? null : null,
    };
  });

  // Build segments between consecutive points with speed colors
  const segments = [];
  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];
    const speed = rawSpeeds[i] ?? null;
    segments.push({
      id: `seg-${i}`,
      fromIndex: i + 1,
      toIndex: i + 2,
      coordinates: [
        [p1.lat, p1.lng],
        [p2.lat, p2.lng],
      ],
      speed,
      color: getSpeedColor(speed),
    });
  }

  return {
    plate: rawGeoJson.plate || "",
    points,
    segments,
    totalSightings: points.length,
  };
}

export function useTrajectory(initialPlate = null) {
  const [plate, setPlate] = useState(initialPlate);
  const [data, setData] = useState({
    plate: "",
    points: [],
    segments: [],
    totalSightings: 0,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchTrajectory = useCallback(async (targetPlate, fromDate = null, toDate = null) => {
    if (!targetPlate) {
      setData({ plate: "", points: [], segments: [], totalSightings: 0 });
      return;
    }

    setLoading(true);
    setError(null);
    setPlate(targetPlate);

    try {
      const params = {};
      if (fromDate) params.from = fromDate;
      if (toDate) params.to = toDate;

      const response = await apiClient.get(`/vehicles/${encodeURIComponent(targetPlate)}/trajectory`, {
        params,
      });

      const parsed = parseTrajectoryData(response.data);
      setData(parsed);
      return parsed;
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || "Failed to load trajectory";
      setError(msg);
      setData({ plate: targetPlate, points: [], segments: [], totalSightings: 0 });
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const appendSighting = useCallback((newSighting) => {
    setData((prev) => {
      // Extract properties
      const props = newSighting.properties || newSighting.sighting || newSighting;
      const coords = newSighting.geometry?.coordinates;
      const lat = Number(props.latitude ?? coords?.[1] ?? 0);
      const lng = Number(props.longitude ?? coords?.[0] ?? 0);
      const timestamp = props.timestamp || new Date().toISOString();

      const lastPoint = prev.points[prev.points.length - 1];

      // Calculate speed if there was a previous point
      let calculatedSpeed = null;
      if (lastPoint) {
        const distKm = haversineDistanceKm(lastPoint.lat, lastPoint.lng, lat, lng);
        const dtSec = Math.max(1, (new Date(timestamp).getTime() - new Date(lastPoint.timestamp).getTime()) / 1000);
        calculatedSpeed = Math.round((distKm / (dtSec / 3600.0)) * 100) / 100;
      }

      const newPoint = {
        id: props.id || `live-${Date.now()}`,
        markerIndex: prev.points.length + 1,
        lat,
        lng,
        cameraName: props.camera_name || props.camera || "Live Camera",
        timestamp,
        dwellSeconds: props.dwell_seconds ?? null,
        ocrConfidence: props.ocr_confidence ?? 1.0,
        snapshotUrl: props.snapshot_url || null,
        plate: props.plate || props.plate_number || prev.plate,
        estimatedSpeed: calculatedSpeed,
      };

      const updatedPoints = [...prev.points, newPoint];

      // Re-create or append segment
      const updatedSegments = [...prev.segments];
      if (lastPoint) {
        updatedSegments.push({
          id: `seg-${prev.segments.length}`,
          fromIndex: lastPoint.markerIndex,
          toIndex: newPoint.markerIndex,
          coordinates: [
            [lastPoint.lat, lastPoint.lng],
            [newPoint.lat, newPoint.lng],
          ],
          speed: calculatedSpeed,
          color: getSpeedColor(calculatedSpeed),
        });
      }

      return {
        ...prev,
        points: updatedPoints,
        segments: updatedSegments,
        totalSightings: updatedPoints.length,
      };
    });
  }, []);

  useEffect(() => {
    if (initialPlate) {
      fetchTrajectory(initialPlate);
    }
  }, [initialPlate, fetchTrajectory]);

  return {
    plate,
    setPlate,
    trajectory: data,
    loading,
    error,
    fetchTrajectory,
    appendSighting,
  };
}

export default useTrajectory;
