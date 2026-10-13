import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  getSpeedColor,
  getSpeedCategory,
  haversineDistanceKm,
  parseTrajectoryData,
  useTrajectory,
} from "../hooks/useTrajectory";
import apiClient from "../api/client";

vi.mock("../api/client", () => ({
  default: {
    get: vi.fn(),
  },
}));

describe("useTrajectory & Speed Utilities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("getSpeedColor() thresholds", () => {
    it("returns green (#10b981) for speed < 40 km/h", () => {
      expect(getSpeedColor(0)).toBe("#10b981");
      expect(getSpeedColor(25.5)).toBe("#10b981");
      expect(getSpeedColor(39.9)).toBe("#10b981");
    });

    it("returns amber (#f59e0b) for speed between 40 and 80 km/h", () => {
      expect(getSpeedColor(40)).toBe("#f59e0b");
      expect(getSpeedColor(65.2)).toBe("#f59e0b");
      expect(getSpeedColor(80)).toBe("#f59e0b");
    });

    it("returns red (#ef4444) for speed > 80 km/h", () => {
      expect(getSpeedColor(80.1)).toBe("#ef4444");
      expect(getSpeedColor(120)).toBe("#ef4444");
      expect(getSpeedColor(160)).toBe("#ef4444");
    });

    it("returns default green if speed is null or undefined", () => {
      expect(getSpeedColor(null)).toBe("#10b981");
      expect(getSpeedColor(undefined)).toBe("#10b981");
    });
  });

  describe("haversineDistanceKm()", () => {
    it("computes accurate distance between two geographic coordinates", () => {
      // Kathipara (13.0067, 80.2030) to Chennai Airport (12.9806, 80.1634) ~5.2 km
      const dist = haversineDistanceKm(13.0067, 80.203, 12.9806, 80.1634);
      expect(dist).toBeGreaterThan(4.5);
      expect(dist).toBeLessThan(6.0);
    });
  });

  describe("parseTrajectoryData()", () => {
    const mockGeoJson = {
      type: "FeatureCollection",
      plate: "TN01TJ9999",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [80.1634, 12.9806] },
          properties: {
            camera_name: "CAM-GST-02",
            timestamp: "2026-10-10T08:05:00Z",
            dwell_seconds: 300,
            ocr_confidence: 0.94,
            snapshot_url: "/snapshots/s2.jpg",
          },
        },
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [80.203, 13.0067] },
          properties: {
            camera_name: "CAM-GST-01",
            timestamp: "2026-10-10T08:00:00Z",
            dwell_seconds: 300,
            ocr_confidence: 0.98,
            snapshot_url: "/snapshots/s1.jpg",
          },
        },
        {
          type: "Feature",
          geometry: {
            type: "LineString",
            coordinates: [
              [80.203, 13.0067],
              [80.1634, 12.9806],
            ],
          },
          properties: {
            segment_speeds: [62.4],
          },
        },
      ],
    };

    it("sorts points in chronological order and assigns sequential 1-based marker indices", () => {
      const parsed = parseTrajectoryData(mockGeoJson);

      expect(parsed.plate).toBe("TN01TJ9999");
      expect(parsed.totalSightings).toBe(2);

      // Point 1 should be the earlier timestamp (08:00:00)
      expect(parsed.points[0].markerIndex).toBe(1);
      expect(parsed.points[0].cameraName).toBe("CAM-GST-01");
      expect(parsed.points[0].timestamp).toBe("2026-10-10T08:00:00Z");

      // Point 2 should be the later timestamp (08:05:00)
      expect(parsed.points[1].markerIndex).toBe(2);
      expect(parsed.points[1].cameraName).toBe("CAM-GST-02");
      expect(parsed.points[1].timestamp).toBe("2026-10-10T08:05:00Z");
    });

    it("builds polyline segments with speed and color coding", () => {
      const parsed = parseTrajectoryData(mockGeoJson);
      expect(parsed.segments).toHaveLength(1);

      const seg = parsed.segments[0];
      expect(seg.speed).toBe(62.4);
      expect(seg.color).toBe("#f59e0b"); // 40-80 km/h is amber
      expect(seg.coordinates).toEqual([
        [13.0067, 80.203],
        [12.9806, 80.1634],
      ]);
    });
  });

  describe("useTrajectory hook execution", () => {
    it("fetches and sets trajectory on fetchTrajectory call", async () => {
      const mockApiData = {
        type: "FeatureCollection",
        plate: "KA01AB1234",
        features: [
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: [80.203, 13.0067] },
            properties: {
              camera_name: "CAM-01",
              timestamp: "2026-10-10T10:00:00Z",
              dwell_seconds: 60,
              ocr_confidence: 0.99,
            },
          },
        ],
      };

      apiClient.get.mockResolvedValueOnce({ data: mockApiData });

      const { result } = renderHook(() => useTrajectory());

      await act(async () => {
        await result.current.fetchTrajectory("KA01AB1234");
      });

      expect(apiClient.get).toHaveBeenCalledWith("/vehicles/KA01AB1234/trajectory", {
        params: {},
      });
      expect(result.current.trajectory.points).toHaveLength(1);
      expect(result.current.trajectory.plate).toBe("KA01AB1234");
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBe(null);
    });

    it("appends new sightings live with appendSighting", async () => {
      const { result } = renderHook(() => useTrajectory());

      // Append point 1
      act(() => {
        result.current.appendSighting({
          properties: {
            plate: "TN01AA0001",
            latitude: 13.0067,
            longitude: 80.203,
            camera_name: "CAM-01",
            timestamp: "2026-10-10T12:00:00Z",
          },
        });
      });

      expect(result.current.trajectory.points).toHaveLength(1);
      expect(result.current.trajectory.points[0].markerIndex).toBe(1);

      // Append point 2 (5 mins later, ~5km away -> ~60 km/h)
      act(() => {
        result.current.appendSighting({
          properties: {
            plate: "TN01AA0001",
            latitude: 12.9806,
            longitude: 80.1634,
            camera_name: "CAM-02",
            timestamp: "2026-10-10T12:05:00Z",
          },
        });
      });

      expect(result.current.trajectory.points).toHaveLength(2);
      expect(result.current.trajectory.points[1].markerIndex).toBe(2);
      expect(result.current.trajectory.segments).toHaveLength(1);
      expect(result.current.trajectory.segments[0].color).toBe("#f59e0b"); // amber ~60 km/h
    });
  });
});
