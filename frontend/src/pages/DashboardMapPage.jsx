import React, { useState, useEffect, useRef, useCallback } from "react";
import * as maplibregl from "maplibre-gl";
import apiClient from "../api/client";
import { useTrajectory, getSpeedColor } from "../hooks/useTrajectory";
import { useWebSocket } from "../hooks/useWebSocket";
import {
  Search,
  Play,
  Pause,
  RotateCcw,
  Camera as CameraIcon,
  Layers,
} from "lucide-react";

// Default center: Chennai Corridor (Kathipara - ORR)
const DEFAULT_CENTER = [80.1491, 12.9675]; // [lng, lat]

// High-reliability map styles for RoadTrace AI
export const MAP_STYLES = {
  cartoDark: {
    id: "cartoDark",
    label: "Dark Matter",
    style: {
      version: 8,
      glyphs: "https://tiles.basemaps.cartocdn.com/fonts/{fontstack}/{range}.pbf",
      sources: {
        "carto-dark-tiles": {
          type: "raster",
          tiles: [
            "https://a.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png",
            "https://b.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png",
            "https://c.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png",
            "https://d.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png",
          ],
          tileSize: 256,
          attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
        },
      },
      layers: [
        {
          id: "carto-dark-base",
          type: "raster",
          source: "carto-dark-tiles",
          minzoom: 0,
          maxzoom: 20,
        },
      ],
    },
  },
  osm: {
    id: "osm",
    label: "OpenStreetMap",
    style: {
      version: 8,
      glyphs: "https://tiles.basemaps.cartocdn.com/fonts/{fontstack}/{range}.pbf",
      sources: {
        "osm-tiles": {
          type: "raster",
          tiles: [
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
          ],
          tileSize: 256,
          attribution: "&copy; OpenStreetMap contributors",
        },
      },
      layers: [
        {
          id: "osm-layer",
          type: "raster",
          source: "osm-tiles",
          minzoom: 0,
          maxzoom: 19,
        },
      ],
    },
  },
  vectorDark: {
    id: "vectorDark",
    label: "Vector Dark GL",
    style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  },
  voyager: {
    id: "voyager",
    label: "Voyager",
    style: {
      version: 8,
      glyphs: "https://tiles.basemaps.cartocdn.com/fonts/{fontstack}/{range}.pbf",
      sources: {
        "voyager-tiles": {
          type: "raster",
          tiles: [
            "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
            "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
            "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
            "https://d.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
          ],
          tileSize: 256,
          attribution: "&copy; OpenStreetMap contributors &copy; CARTO",
        },
      },
      layers: [
        {
          id: "voyager-layer",
          type: "raster",
          source: "voyager-tiles",
          minzoom: 0,
          maxzoom: 20,
        },
      ],
    },
  },
};

/**
 * Calculate geographical bearing between two points in degrees (0 = North, 90 = East).
 */
function calculateBearing(lat1, lon1, lat2, lon2) {
  const phi1 = (lat1 * Math.PI) / 180;
  const phi2 = (lat2 * Math.PI) / 180;
  const deltaLambda = ((lon2 - lon1) * Math.PI) / 180;

  const y = Math.sin(deltaLambda) * Math.cos(phi2);
  const x =
    Math.cos(phi1) * Math.sin(phi2) -
    Math.sin(phi1) * Math.cos(phi2) * Math.cos(deltaLambda);
  const brng = (Math.atan2(y, x) * 180) / Math.PI;
  return (brng + 360) % 360;
}

/**
 * Programmatically generate directional arrow icon for MapLibre GL symbol-placement: "line".
 * Points East (along positive X axis, matching 0° line traversal direction).
 */
function registerTrajectoryArrowImage(map) {
  if (!map || map.hasImage("trajectory-arrow")) return;

  const size = 32;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");

  ctx.clearRect(0, 0, size, size);

  // Sleek directional chevron
  ctx.beginPath();
  ctx.moveTo(size * 0.18, size * 0.22);
  ctx.lineTo(size * 0.82, size * 0.5);
  ctx.lineTo(size * 0.18, size * 0.78);
  ctx.lineTo(size * 0.35, size * 0.5);
  ctx.closePath();

  ctx.fillStyle = "#ffffff";
  ctx.shadowColor = "rgba(0, 0, 0, 0.9)";
  ctx.shadowBlur = 4;
  ctx.fill();

  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "rgba(0, 0, 0, 0.85)";
  ctx.stroke();

  const imageData = ctx.getImageData(0, 0, size, size);
  map.addImage("trajectory-arrow", imageData);
}

/**
 * Ensure trajectory GeoJSON source and layers (glow, casing, lines, directional arrows) exist on the map.
 */
function ensureTrajectoryLayers(map) {
  if (!map || !map.isStyleLoaded()) return;

  registerTrajectoryArrowImage(map);

  if (!map.getSource("trajectory-segments")) {
    map.addSource("trajectory-segments", {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: [],
      },
    });

    // Layer 1: Pulsing glow layer for high-speed (> 80 km/h) segments
    map.addLayer({
      id: "trajectory-glow",
      type: "line",
      source: "trajectory-segments",
      filter: [">=", ["get", "speed"], 80],
      layout: {
        "line-join": "round",
        "line-cap": "round",
      },
      paint: {
        "line-color": "#ef4444",
        "line-width": 14,
        "line-opacity": 0.5,
        "line-blur": 6,
      },
    });

    // Layer 2: Black casing for high contrast on dark tiles
    map.addLayer({
      id: "trajectory-casing",
      type: "line",
      source: "trajectory-segments",
      layout: {
        "line-join": "round",
        "line-cap": "round",
      },
      paint: {
        "line-color": "#000000",
        "line-width": 7.5,
        "line-opacity": 0.85,
      },
    });

    // Layer 3: Main velocity-colored trajectory lines
    map.addLayer({
      id: "trajectory-lines",
      type: "line",
      source: "trajectory-segments",
      layout: {
        "line-join": "round",
        "line-cap": "round",
      },
      paint: {
        "line-color": ["get", "color"],
        "line-width": 4.5,
        "line-opacity": 0.95,
      },
    });

    // Layer 4: Directional arrows along line traversal
    map.addLayer({
      id: "trajectory-arrows",
      type: "symbol",
      source: "trajectory-segments",
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": 65,
        "icon-image": "trajectory-arrow",
        "icon-size": 0.55,
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        "icon-rotation-alignment": "map",
      },
    });
  }
}

/**
 * Ensure camera clustering GeoJSON source and cluster/unclustered layers exist on the map.
 */
function ensureCameraLayers(map, onCameraClick) {
  if (!map || !map.isStyleLoaded()) return;

  if (!map.getSource("cameras-source")) {
    map.addSource("cameras-source", {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: [],
      },
      cluster: true,
      clusterMaxZoom: 14,
      clusterRadius: 50,
    });

    // 1. Cluster circles with stepped colors & sizes
    map.addLayer({
      id: "camera-clusters",
      type: "circle",
      source: "cameras-source",
      filter: ["has", "point_count"],
      paint: {
        "circle-color": [
          "step",
          ["get", "point_count"],
          "#3b82f6", // blue < 5
          5,
          "#10b981", // emerald 5 - 14
          15,
          "#f59e0b", // amber 15+
        ],
        "circle-radius": [
          "step",
          ["get", "point_count"],
          18,
          5,
          24,
          15,
          30,
        ],
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
      },
    });

    // 2. Cluster count text
    map.addLayer({
      id: "camera-cluster-count",
      type: "symbol",
      source: "cameras-source",
      filter: ["has", "point_count"],
      layout: {
        "text-field": "{point_count_abbreviated}",
        "text-font": ["Open Sans Regular", "Roboto Regular"],
        "text-size": 12,
      },
      paint: {
        "text-color": "#ffffff",
      },
    });

    // 3. Unclustered camera marker outer circle
    map.addLayer({
      id: "camera-unclustered",
      type: "circle",
      source: "cameras-source",
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": "#171717",
        "circle-radius": 7.5,
        "circle-stroke-width": 2,
        "circle-stroke-color": [
          "case",
          ["==", ["get", "status"], "active"],
          "#10b981",
          "#737373",
        ],
      },
    });

    // 4. Unclustered camera inner core dot
    map.addLayer({
      id: "camera-unclustered-inner",
      type: "circle",
      source: "cameras-source",
      filter: ["!", ["has", "point_count"]],
      paint: {
        "circle-color": [
          "case",
          ["==", ["get", "status"], "active"],
          "#34d399",
          "#a3a3a3",
        ],
        "circle-radius": 3,
      },
    });

    // Interactivity: Cluster click zooms in
    map.on("click", "camera-clusters", (e) => {
      const features = map.queryRenderedFeatures(e.point, {
        layers: ["camera-clusters"],
      });
      if (!features.length) return;
      const clusterId = features[0].properties.cluster_id;
      const source = map.getSource("cameras-source");
      if (source && source.getClusterExpansionZoom) {
        source.getClusterExpansionZoom(clusterId, (err, zoom) => {
          if (err) return;
          map.easeTo({
            center: features[0].geometry.coordinates,
            zoom: zoom + 0.5,
            duration: 500,
          });
        });
      }
    });

    // Interactivity: Unclustered camera click displays rich popup
    map.on("click", "camera-unclustered", (e) => {
      if (!e.features || !e.features.length) return;
      const feat = e.features[0];
      const coords = feat.geometry.coordinates.slice();
      const props = feat.properties;
      if (onCameraClick) {
        onCameraClick(props, coords);
      }
    });

    // Cursor pointer on hover
    map.on("mouseenter", "camera-clusters", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "camera-clusters", () => {
      map.getCanvas().style.cursor = "";
    });
    map.on("mouseenter", "camera-unclustered", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "camera-unclustered", () => {
      map.getCanvas().style.cursor = "";
    });
  }
}

export function DashboardMapPage({ initialSearchPlate = null, onPlateSelect = null }) {
  const mapContainerRef = useRef(null);
  const mapRef = useRef(null);
  const [isMapReady, setIsMapReady] = useState(false);

  const [searchInput, setSearchInput] = useState(initialSearchPlate || "");
  const [cameras, setCameras] = useState([]);
  const [loadingCameras, setLoadingCameras] = useState(false);
  const [showCameras, setShowCameras] = useState(true);
  const [seededVehicles, setSeededVehicles] = useState([]);

  // Trajectory state
  const {
    plate,
    setPlate,
    trajectory,
    loading: trajectoryLoading,
    error: trajectoryError,
    fetchTrajectory,
    appendSighting,
  } = useTrajectory(initialSearchPlate);

  // Live WebSocket
  const [liveSightingCount, setLiveSightingCount] = useState(0);
  const { isConnected: isWsConnected, status: wsStatus } = useWebSocket(
    plate,
    (incomingSighting) => {
      appendSighting(incomingSighting);
      setLiveSightingCount((prev) => prev + 1);
    }
  );

  // Timeline playback state
  const [sliderIndex, setSliderIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const animFrameRef = useRef(null);
  const glowAnimFrameRef = useRef(null);

  // Marker references for MapLibre
  const trajectoryMarkersRef = useRef([]);
  const vehicleCursorRef = useRef(null);
  const cameraPopupRef = useRef(null);

  const [currentStyle, setCurrentStyle] = useState("cartoDark");

  // 1. Initialize MapLibre GL
  useEffect(() => {
    if (!mapContainerRef.current) return;

    const initialStyleConfig = MAP_STYLES[currentStyle]?.style || MAP_STYLES.cartoDark.style;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: initialStyleConfig,
      center: DEFAULT_CENTER,
      zoom: 12,
      attributionControl: true,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

    const handleCameraPopup = (props, coords) => {
      if (cameraPopupRef.current) {
        cameraPopupRef.current.remove();
      }
      const popupHtml = `
        <div class="p-3 font-mono text-xs max-w-xs">
          <div class="font-bold text-white text-sm border-b border-neutral-800 pb-1 mb-2 flex items-center justify-between">
            <span>${props.name}</span>
            <span class="text-[10px] text-emerald-400 uppercase bg-emerald-950/60 px-1 rounded">${props.status}</span>
          </div>
          <div class="space-y-1 text-neutral-300">
            <p class="text-[11px]"><span class="text-neutral-500">Location: </span>${props.intersection_name || "Surveillance Point"}</p>
            <p class="text-[11px]"><span class="text-neutral-500">Coordinates: </span>${Number(coords[1]).toFixed(4)}, ${Number(coords[0]).toFixed(4)}</p>
            <p class="text-[11px]"><span class="text-neutral-500">Heading: </span>${props.heading_deg}°</p>
          </div>
        </div>
      `;
      cameraPopupRef.current = new maplibregl.Popup({ offset: 12, className: "swiss-maplibre-popup" })
        .setLngLat(coords)
        .setHTML(popupHtml)
        .addTo(map);
    };

    const setupLayers = () => {
      if (!map.isStyleLoaded()) return;
      ensureTrajectoryLayers(map);
      ensureCameraLayers(map, handleCameraPopup);
      setIsMapReady(true);
      map.resize();
    };

    map.on("load", setupLayers);
    map.on("styledata", () => {
      if (map.isStyleLoaded()) {
        setupLayers();
      }
    });

    // Handle fallback if vector style encounters error
    map.on("error", (e) => {
      console.warn("MapLibre event error:", e);
      if (e?.error?.message?.includes("style") || e?.error?.message?.includes("404")) {
        try {
          map.setStyle(MAP_STYLES.cartoDark.style);
        } catch {}
      }
    });

    // Responsive map resize observer
    const resizeObserver = new ResizeObserver(() => {
      if (map) map.resize();
    });
    resizeObserver.observe(mapContainerRef.current);

    mapRef.current = map;

    return () => {
      setIsMapReady(false);
      resizeObserver.disconnect();
      if (cameraPopupRef.current) {
        cameraPopupRef.current.remove();
      }
      trajectoryMarkersRef.current.forEach(({ marker }) => marker.remove());
      trajectoryMarkersRef.current = [];
      if (vehicleCursorRef.current) {
        vehicleCursorRef.current.remove();
        vehicleCursorRef.current = null;
      }
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      if (glowAnimFrameRef.current) cancelAnimationFrame(glowAnimFrameRef.current);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // 2. Fetch cameras and sample seeded vehicles
  useEffect(() => {
    const loadInitialData = async () => {
      setLoadingCameras(true);
      try {
        const camRes = await apiClient.get("/cameras");
        setCameras(camRes.data || []);
      } catch (err) {
        console.error("Failed to load cameras:", err);
      } finally {
        setLoadingCameras(false);
      }

      try {
        const searchRes = await apiClient.get("/search?plate=TN");
        if (searchRes.data?.results?.length > 0) {
          setSeededVehicles(searchRes.data.results.slice(0, 5));
        }
      } catch {
        // ignore
      }
    };
    loadInitialData();
  }, []);

  // 3. Update Camera Clustering GeoJSON Source & Visibility
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    const source = map.getSource("cameras-source");
    if (source) {
      const cameraFeatures = cameras.map((cam) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [Number(cam.longitude), Number(cam.latitude)],
        },
        properties: {
          id: cam.id,
          name: cam.name,
          status: cam.status,
          intersection_name: cam.intersection_name,
          heading_deg: cam.heading_deg,
          latitude: cam.latitude,
          longitude: cam.longitude,
        },
      }));

      source.setData({
        type: "FeatureCollection",
        features: cameraFeatures,
      });

      // Fit to camera bounds if no trajectory is active yet
      if (trajectory.points.length === 0 && cameras.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        cameras.forEach((c) => bounds.extend([c.longitude, c.latitude]));
        map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 600 });
      }
    }

    // Toggle camera cluster layers visibility
    const visibility = showCameras ? "visible" : "none";
    [
      "camera-clusters",
      "camera-cluster-count",
      "camera-unclustered",
      "camera-unclustered-inner",
    ].forEach((layerId) => {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", visibility);
      }
    });
  }, [cameras, showCameras, isMapReady, trajectory.points.length]);

  // 4. Update Trajectory Polylines (Road-snapped GeoJSON lines with speed colors)
  const updateTrajectoryPolylines = useCallback(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    ensureTrajectoryLayers(map);

    const features = trajectory.segments.map((seg) => {
      // Use road-snapped coordinates from backend if available, fallback to straight line
      const coords =
        seg.geoJsonCoordinates ||
        seg.coordinates.map((c) => [c[1], c[0]]); // GeoJSON is [lng, lat]

      return {
        type: "Feature",
        properties: {
          id: seg.id,
          speed: seg.speed,
          color: seg.color,
        },
        geometry: {
          type: "LineString",
          coordinates: coords,
        },
      };
    });

    const source = map.getSource("trajectory-segments");
    if (source) {
      source.setData({
        type: "FeatureCollection",
        features,
      });
    }
  }, [trajectory.segments, isMapReady]);

  useEffect(() => {
    updateTrajectoryPolylines();
  }, [updateTrajectoryPolylines]);

  // 5. High-Speed Segment Pulsing Glow Animation
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    const hasHighSpeed = trajectory.segments.some((s) => s.speed !== null && s.speed >= 80);

    if (hasHighSpeed) {
      const animateGlow = () => {
        if (!mapRef.current || !mapRef.current.getLayer("trajectory-glow")) return;
        const now = Date.now();
        const pulse = 0.5 + 0.5 * Math.sin(now / 300); // 0.0 -> 1.0
        const opacity = 0.25 + 0.45 * pulse;
        const width = 11 + 4 * pulse;

        try {
          mapRef.current.setPaintProperty("trajectory-glow", "line-opacity", opacity);
          mapRef.current.setPaintProperty("trajectory-glow", "line-width", width);
        } catch {}

        glowAnimFrameRef.current = requestAnimationFrame(animateGlow);
      };

      glowAnimFrameRef.current = requestAnimationFrame(animateGlow);
    }

    return () => {
      if (glowAnimFrameRef.current) {
        cancelAnimationFrame(glowAnimFrameRef.current);
      }
    };
  }, [trajectory.segments, isMapReady]);

  // 6. Chronological Numbered Markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    trajectoryMarkersRef.current.forEach(({ marker }) => marker.remove());
    trajectoryMarkersRef.current = [];

    trajectory.points.forEach((pt, idx) => {
      const el = document.createElement("div");
      el.className = `swiss-marker ${sliderIndex === idx ? "active" : ""}`;
      el.innerHTML = `<span>${pt.markerIndex}</span>`;
      el.addEventListener("click", () => {
        setSliderIndex(idx);
      });

      const popupHtml = `
        <div class="p-3 font-mono text-xs w-64 bg-neutral-900 rounded">
          <div class="flex items-center justify-between border-b border-neutral-800 pb-1 mb-2">
            <span class="font-bold text-white text-sm">Marker #${pt.markerIndex}</span>
            <span class="text-[11px] font-semibold text-neutral-300 bg-neutral-800 px-1.5 py-0.5 rounded">${pt.plate}</span>
          </div>
          <div class="space-y-1.5 text-neutral-300 text-[11px]">
            <div class="flex justify-between">
              <span class="text-neutral-500">Camera:</span>
              <span class="text-white font-semibold">${pt.cameraName}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-neutral-500">Timestamp:</span>
              <span class="text-neutral-200">${new Date(pt.timestamp).toLocaleTimeString()}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-neutral-500">Dwell Time:</span>
              <span class="text-neutral-200">${pt.dwellSeconds !== null && pt.dwellSeconds !== undefined ? `${Math.round(pt.dwellSeconds)}s` : "Terminal / Active"}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-neutral-500">Est. Speed:</span>
              <span class="font-bold" style="color: ${getSpeedColor(pt.estimatedSpeed)}">${pt.estimatedSpeed !== null ? `${pt.estimatedSpeed} km/h` : "Origin Point"}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-neutral-500">OCR Conf:</span>
              <span class="text-emerald-400 font-semibold">${pt.ocrConfidence !== null ? `${Math.round(pt.ocrConfidence * 100)}%` : "99%"}</span>
            </div>
          </div>
          ${pt.snapshotUrl ? `
            <div class="mt-3 border border-neutral-800 rounded overflow-hidden">
              <img src="${pt.snapshotUrl}" alt="Plate snapshot" class="w-full h-24 object-cover bg-neutral-950" />
            </div>
          ` : `
            <div class="mt-2.5 p-2 bg-neutral-950 border border-neutral-800 rounded flex items-center justify-center space-x-1 text-neutral-500 text-[10px]">
              <svg class="w-3 h-3 mr-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
              <span>Snapshot captured in DB</span>
            </div>
          `}
        </div>
      `;

      const popup = new maplibregl.Popup({ offset: 18, className: "swiss-maplibre-popup" })
        .setHTML(popupHtml);

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([pt.lng, pt.lat])
        .setPopup(popup)
        .addTo(map);

      trajectoryMarkersRef.current.push({ marker, el, index: idx });
    });

    // Fit map bounds to points
    if (trajectory.points.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      trajectory.points.forEach((p) => bounds.extend([p.lng, p.lat]));
      map.fitBounds(bounds, { padding: 80, maxZoom: 15, duration: 800 });
    }
  }, [trajectory.points, isMapReady]);

  // 7. Highlight active marker on slider change
  useEffect(() => {
    trajectoryMarkersRef.current.forEach(({ el, index }) => {
      if (index === sliderIndex) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });
  }, [sliderIndex]);

  // 8. Vehicle Animated Cursor Marker creation and static orientation update
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    const currentPoint = trajectory.points[sliderIndex] || null;

    if (currentPoint) {
      // Determine initial orientation bearing
      let bearing = 0;
      if (sliderIndex < trajectory.points.length - 1) {
        const nextPoint = trajectory.points[sliderIndex + 1];
        bearing = calculateBearing(currentPoint.lat, currentPoint.lng, nextPoint.lat, nextPoint.lng);
      } else if (sliderIndex > 0) {
        const prevPoint = trajectory.points[sliderIndex - 1];
        bearing = calculateBearing(prevPoint.lat, prevPoint.lng, currentPoint.lat, currentPoint.lng);
      }

      if (!vehicleCursorRef.current) {
        const container = document.createElement("div");
        container.className = "swiss-vehicle-cursor-container";
        container.innerHTML = `
          <div class="swiss-vehicle-pulse"></div>
          <div class="swiss-vehicle-cursor">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z" />
            </svg>
          </div>
        `;

        const marker = new maplibregl.Marker({ element: container, rotationAlignment: "map" })
          .setLngLat([currentPoint.lng, currentPoint.lat])
          .setRotation(bearing)
          .addTo(map);

        vehicleCursorRef.current = marker;
      } else {
        // If not running smooth playback animation, directly update position & rotation
        if (!isPlaying) {
          vehicleCursorRef.current.setLngLat([currentPoint.lng, currentPoint.lat]);
          vehicleCursorRef.current.setRotation(bearing);
        }
      }
    } else {
      if (vehicleCursorRef.current) {
        vehicleCursorRef.current.remove();
        vehicleCursorRef.current = null;
      }
    }
  }, [sliderIndex, trajectory.points, isMapReady, isPlaying]);

  // 9. Update slider bounds when points change
  useEffect(() => {
    if (trajectory.points.length > 0) {
      setSliderIndex(trajectory.points.length - 1);
    } else {
      setSliderIndex(0);
    }
  }, [trajectory.points.length]);

  // 10. Smooth Playback Animation with Road Interpolation & Rotation
  useEffect(() => {
    if (!isPlaying || trajectory.points.length < 2) {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      return;
    }

    let currentSegmentIndex = sliderIndex;
    if (currentSegmentIndex >= trajectory.points.length - 1) {
      currentSegmentIndex = 0;
      setSliderIndex(0);
    }

    const segmentDuration = 1400 / playbackSpeed;
    let startTime = performance.now();

    const animateVehicle = (currentTime) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / segmentDuration, 1.0);

      const segment = trajectory.segments[currentSegmentIndex];
      // Segment coordinates in GeoJSON [lng, lat]
      const coords =
        segment?.geoJsonCoordinates ||
        (segment?.coordinates
          ? segment.coordinates.map((c) => [c[1], c[0]])
          : null);

      if (coords && coords.length >= 2 && vehicleCursorRef.current) {
        // Find position along polyline
        const totalSteps = coords.length - 1;
        const floatIndex = progress * totalSteps;
        const subIndex = Math.min(Math.floor(floatIndex), totalSteps - 1);
        const subFrac = floatIndex - subIndex;

        const pA = coords[subIndex];
        const pB = coords[subIndex + 1] || coords[subIndex];

        const interpLng = pA[0] + (pB[0] - pA[0]) * subFrac;
        const interpLat = pA[1] + (pB[1] - pA[1]) * subFrac;

        const bearing = calculateBearing(pA[1], pA[0], pB[1], pB[0]);

        vehicleCursorRef.current.setLngLat([interpLng, interpLat]);
        vehicleCursorRef.current.setRotation(bearing);
      }

      if (progress < 1.0) {
        animFrameRef.current = requestAnimationFrame(animateVehicle);
      } else {
        // Advance to next waypoint
        const nextIndex = currentSegmentIndex + 1;
        setSliderIndex(nextIndex);

        if (nextIndex < trajectory.points.length - 1) {
          currentSegmentIndex = nextIndex;
          startTime = performance.now();
          animFrameRef.current = requestAnimationFrame(animateVehicle);
        } else {
          // Reached destination
          setIsPlaying(false);
        }
      }
    };

    animFrameRef.current = requestAnimationFrame(animateVehicle);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [isPlaying, trajectory.points.length, trajectory.segments, playbackSpeed, sliderIndex]);

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    const clean = searchInput.trim().toUpperCase();
    if (clean) {
      setPlate(clean);
      fetchTrajectory(clean);
      setLiveSightingCount(0);
      if (onPlateSelect) onPlateSelect(clean);
    }
  };

  const handleQuickSelect = (plateNum) => {
    setSearchInput(plateNum);
    setPlate(plateNum);
    fetchTrajectory(plateNum);
    setLiveSightingCount(0);
    if (onPlateSelect) onPlateSelect(plateNum);
  };

  const currentPoint = trajectory.points[sliderIndex] || null;

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)] bg-neutral-950 overflow-hidden font-sans">
      {/* Top Swiss Status & Command Ribbon */}
      <div className="border-b border-neutral-800 bg-neutral-900/90 px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
        {/* Search Plate Box */}
        <form onSubmit={handleSearchSubmit} className="flex items-center space-x-2">
          <div className="relative">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="ENTER PLATE (e.g. TN01TJ...)"
              className="w-56 sm:w-72 px-3 py-1.5 pl-8 bg-neutral-950 border border-neutral-700 rounded text-xs text-white placeholder-neutral-500 font-mono uppercase focus:outline-none focus:border-white focus:ring-1 focus:ring-white transition"
            />
            <Search className="w-3.5 h-3.5 text-neutral-400 absolute left-2.5 top-2" />
          </div>
          <button
            type="submit"
            disabled={trajectoryLoading}
            className="px-3 py-1.5 bg-white hover:bg-neutral-200 text-black font-semibold text-xs uppercase tracking-wider rounded transition flex items-center space-x-1 font-mono disabled:opacity-50"
          >
            <span>Trace</span>
          </button>
        </form>

        {/* Quick Plate Presets */}
        <div className="hidden lg:flex items-center space-x-2">
          <span className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">
            Recent / Seeded:
          </span>
          {seededVehicles.length > 0 ? (
            seededVehicles.map((v) => (
              <button
                key={v.plate_number}
                onClick={() => handleQuickSelect(v.plate_number)}
                className={`px-2 py-0.5 rounded text-[10px] font-mono border transition ${
                  plate === v.plate_number
                    ? "bg-white text-black border-white font-bold"
                    : "bg-neutral-950 text-neutral-300 border-neutral-800 hover:border-neutral-600"
                }`}
              >
                {v.plate_number}
              </button>
            ))
          ) : (
            <span className="text-[10px] font-mono text-neutral-500">Search to trace</span>
          )}
        </div>

        {/* Live WebSocket Status & Speed Legend */}
        <div className="flex items-center space-x-4">
          {plate && (
            <div className="flex items-center space-x-2 px-2.5 py-1 bg-neutral-950 border border-neutral-800 rounded font-mono text-[11px]">
              <span
                className={`w-2 h-2 rounded-full ${
                  isWsConnected
                    ? "bg-emerald-400 animate-ping"
                    : wsStatus === "connecting"
                    ? "bg-amber-400"
                    : "bg-neutral-600"
                }`}
              />
              <span className="text-neutral-300">
                WS: {isWsConnected ? "CONNECTED" : wsStatus.toUpperCase()}
              </span>
              {liveSightingCount > 0 && (
                <span className="px-1.5 py-0.2 bg-emerald-900/60 text-emerald-300 rounded text-[9px]">
                  +{liveSightingCount} live
                </span>
              )}
            </div>
          )}

          {/* Speed Legend */}
          <div className="hidden md:flex items-center space-x-2.5 text-[10px] font-mono border-l border-neutral-800 pl-4">
            <span className="text-neutral-400 uppercase tracking-wider">SPEED:</span>
            <span className="flex items-center space-x-1 text-emerald-400">
              <span className="w-2.5 h-1.5 rounded-sm bg-emerald-500 inline-block" />
              <span>&lt;40</span>
            </span>
            <span className="flex items-center space-x-1 text-amber-400">
              <span className="w-2.5 h-1.5 rounded-sm bg-amber-500 inline-block" />
              <span>40-80</span>
            </span>
            <span className="flex items-center space-x-1 text-red-400">
              <span className="w-2.5 h-1.5 rounded-sm bg-red-500 inline-block" />
              <span>&gt;80 km/h</span>
            </span>
          </div>

          {/* Map Style Selector */}
          <div className="flex items-center space-x-1 bg-neutral-950 border border-neutral-800 rounded p-0.5">
            {Object.entries(MAP_STYLES).map(([key, s]) => (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setCurrentStyle(key);
                  const map = mapRef.current;
                  if (map && MAP_STYLES[key]) {
                    setIsMapReady(false);
                    map.setStyle(MAP_STYLES[key].style);
                  }
                }}
                className={`px-2 py-0.5 rounded text-[10px] font-mono transition ${
                  currentStyle === key
                    ? "bg-white text-black font-bold shadow-sm"
                    : "text-neutral-400 hover:text-white"
                }`}
                title={s.label}
              >
                {s.label}
              </button>
            ))}
          </div>

          {/* Cameras Cluster Toggle */}
          <button
            onClick={() => setShowCameras((prev) => !prev)}
            className={`px-2.5 py-1 rounded text-[11px] font-mono border transition flex items-center space-x-1.5 ${
              showCameras
                ? "bg-neutral-800 text-white border-neutral-700"
                : "bg-neutral-950 text-neutral-400 border-neutral-800"
            }`}
          >
            <CameraIcon className="w-3 h-3" />
            <span>Cameras ({cameras.length})</span>
          </button>
        </div>
      </div>

      {/* Main Map + Side Telemetry Grid */}
      <div className="flex-1 relative flex overflow-hidden">
        {/* MapLibre GL Container with Dark Matter Cartography */}
        <div className="flex-1 relative z-0 h-full w-full">
          <div ref={mapContainerRef} className="w-full h-full min-h-[450px] relative" />
        </div>

        {/* Side Telemetry & Inspection Dock */}
        <div className="w-80 lg:w-96 border-l border-neutral-800 bg-neutral-900/95 flex flex-col justify-between overflow-y-auto">
          {/* Header */}
          <div className="p-4 border-b border-neutral-800">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-mono uppercase tracking-widest text-neutral-400">
                Vehicle Telemetry
              </h2>
              {plate && (
                <span className="px-2 py-0.5 bg-white text-black font-mono font-bold text-xs rounded">
                  {plate}
                </span>
              )}
            </div>

            {trajectory.isRoadSnapped && (
              <div className="mt-2 flex items-center space-x-1 text-[10px] font-mono text-emerald-400 bg-emerald-950/40 border border-emerald-900/60 px-2 py-1 rounded">
                <Layers className="w-3 h-3 mr-1" />
                <span>OSRM Road-Snapped Alignment</span>
              </div>
            )}

            {trajectoryError && (
              <div className="mt-3 p-2.5 bg-red-950/40 border border-red-800 rounded text-red-300 text-xs font-mono">
                {trajectoryError}
              </div>
            )}
          </div>

          {/* Sighting Details */}
          <div className="flex-1 p-4 space-y-4">
            {currentPoint ? (
              <div className="space-y-4">
                {/* Active Sighting Card */}
                <div className="border border-neutral-800 bg-neutral-950 p-3.5 rounded">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[11px] font-mono text-neutral-400">
                      POINT {currentPoint.markerIndex} OF {trajectory.points.length}
                    </span>
                    <span
                      className="text-[11px] font-mono font-bold px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: `${getSpeedColor(currentPoint.estimatedSpeed)}20`,
                        color: getSpeedColor(currentPoint.estimatedSpeed),
                      }}
                    >
                      {currentPoint.estimatedSpeed !== null
                        ? `${currentPoint.estimatedSpeed} km/h`
                        : "START"}
                    </span>
                  </div>

                  <h3 className="text-sm font-semibold text-white tracking-tight">
                    {currentPoint.cameraName}
                  </h3>
                  <p className="text-[11px] font-mono text-neutral-400 mt-0.5">
                    {new Date(currentPoint.timestamp).toLocaleString()}
                  </p>

                  <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-neutral-800 font-mono text-[11px]">
                    <div>
                      <span className="text-neutral-500 block text-[10px]">DWELL TIME</span>
                      <span className="text-neutral-200 font-semibold">
                        {currentPoint.dwellSeconds !== null
                          ? `${Math.round(currentPoint.dwellSeconds)} sec`
                          : "Ongoing"}
                      </span>
                    </div>
                    <div>
                      <span className="text-neutral-500 block text-[10px]">OCR ACCURACY</span>
                      <span className="text-emerald-400 font-semibold">
                        {currentPoint.ocrConfidence !== null
                          ? `${(currentPoint.ocrConfidence * 100).toFixed(1)}%`
                          : "98.5%"}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Sighting Chronological Timeline List */}
                <div>
                  <h4 className="text-[11px] font-mono uppercase tracking-wider text-neutral-400 mb-2">
                    Chronological Sequence
                  </h4>
                  <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                    {trajectory.points.map((pt, idx) => (
                      <div
                        key={pt.id}
                        onClick={() => setSliderIndex(idx)}
                        className={`p-2 rounded cursor-pointer transition border flex items-center justify-between text-xs font-mono ${
                          sliderIndex === idx
                            ? "bg-neutral-800 border-white text-white"
                            : "bg-neutral-950/60 border-neutral-800/80 text-neutral-400 hover:text-neutral-200"
                        }`}
                      >
                        <div className="flex items-center space-x-2">
                          <span className="w-5 h-5 rounded flex items-center justify-center bg-neutral-900 border border-neutral-700 text-[10px] font-bold">
                            {pt.markerIndex}
                          </span>
                          <span className="truncate max-w-[130px]">{pt.cameraName}</span>
                        </div>
                        <span className="text-[10px] text-neutral-400">
                          {new Date(pt.timestamp).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center p-6 border border-dashed border-neutral-800 rounded">
                <Search className="w-8 h-8 text-neutral-600 mb-2" />
                <p className="text-xs font-mono uppercase tracking-wider text-neutral-400">
                  No Vehicle Trajectory Loaded
                </p>
                <p className="text-[11px] text-neutral-500 mt-1 max-w-xs">
                  Enter a license plate above or select a seeded plate to view chronological
                  multi-camera route reconstruction.
                </p>
              </div>
            )}
          </div>

          {/* Timeline Animation Scrubber Controls */}
          {trajectory.points.length > 0 && (
            <div className="p-4 border-t border-neutral-800 bg-neutral-950/90 space-y-3">
              <div className="flex items-center justify-between text-xs font-mono">
                <span className="text-neutral-400">TIMELINE REPLAY</span>
                <span className="text-white font-semibold">
                  T-{sliderIndex + 1} / {trajectory.points.length}
                </span>
              </div>

              {/* Slider */}
              <input
                type="range"
                min="0"
                max={trajectory.points.length - 1}
                value={sliderIndex}
                onChange={(e) => setSliderIndex(Number(e.target.value))}
                className="w-full accent-white bg-neutral-800 h-1.5 rounded cursor-pointer"
              />

              {/* Playback Controls */}
              <div className="flex items-center justify-between pt-1">
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => setIsPlaying(!isPlaying)}
                    className="p-2 bg-white text-black hover:bg-neutral-200 rounded transition"
                    title={isPlaying ? "Pause" : "Play"}
                  >
                    {isPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                  </button>

                  <button
                    onClick={() => {
                      setIsPlaying(false);
                      setSliderIndex(0);
                    }}
                    className="p-2 bg-neutral-900 hover:bg-neutral-800 text-neutral-300 border border-neutral-700 rounded transition"
                    title="Reset to start"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                  </button>
                </div>

                {/* Speed Toggle */}
                <div className="flex items-center space-x-1 font-mono text-[10px]">
                  {[1, 2, 5].map((spd) => (
                    <button
                      key={spd}
                      onClick={() => setPlaybackSpeed(spd)}
                      className={`px-2 py-1 rounded border transition ${
                        playbackSpeed === spd
                          ? "bg-neutral-800 text-white border-neutral-600 font-bold"
                          : "bg-neutral-950 text-neutral-500 border-neutral-800"
                      }`}
                    >
                      {spd}x
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default DashboardMapPage;
