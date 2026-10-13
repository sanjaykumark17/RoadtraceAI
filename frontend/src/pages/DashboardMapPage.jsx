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
  ImageIcon,
} from "lucide-react";

// Default center: Chennai Corridor (Kathipara - ORR)
const DEFAULT_CENTER = [80.1491, 12.9675]; // [lng, lat]
const MAP_STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

function ensureTrajectoryLayers(map) {
  if (!map || !map.isStyleLoaded()) return;

  if (!map.getSource("trajectory-segments")) {
    map.addSource("trajectory-segments", {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: [],
      },
    });

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
        "line-width": 7,
        "line-opacity": 0.8,
      },
    });

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
  const playIntervalRef = useRef(null);

  // Marker references for MapLibre
  const cameraMarkersRef = useRef([]);
  const trajectoryMarkersRef = useRef([]);
  const vehicleCursorRef = useRef(null);

  // 1. Initialize MapLibre GL with OpenFreeMap Liberty style
  useEffect(() => {
    if (!mapContainerRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE_URL,
      center: DEFAULT_CENTER,
      zoom: 12,
      attributionControl: true,
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

    map.on("load", () => {
      ensureTrajectoryLayers(map);
      setIsMapReady(true);
    });

    // Resize observer to ensure responsive map resizing
    const resizeObserver = new ResizeObserver(() => {
      if (map) map.resize();
    });
    resizeObserver.observe(mapContainerRef.current);

    mapRef.current = map;

    return () => {
      setIsMapReady(false);
      resizeObserver.disconnect();
      cameraMarkersRef.current.forEach((m) => m.remove());
      cameraMarkersRef.current = [];
      trajectoryMarkersRef.current.forEach(({ marker }) => marker.remove());
      trajectoryMarkersRef.current = [];
      if (vehicleCursorRef.current) {
        vehicleCursorRef.current.remove();
        vehicleCursorRef.current = null;
      }
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // 2. Fetch cameras and sample vehicles
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

  // 3. Render / Update Camera Markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    // Clear existing camera markers
    cameraMarkersRef.current.forEach((m) => m.remove());
    cameraMarkersRef.current = [];

    if (showCameras && cameras.length > 0) {
      cameras.forEach((cam) => {
        const el = document.createElement("div");
        el.className = "swiss-camera-marker cursor-pointer";
        el.title = `${cam.name} (${cam.status})`;
        el.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>`;

        const popupHtml = `
          <div class="p-3 font-mono text-xs max-w-xs">
            <div class="font-bold text-white text-sm border-b border-neutral-800 pb-1 mb-2 flex items-center justify-between">
              <span>${cam.name}</span>
              <span class="text-[10px] text-emerald-400 uppercase bg-emerald-950/60 px-1 rounded">${cam.status}</span>
            </div>
            <div class="space-y-1 text-neutral-300">
              <p class="text-[11px]"><span class="text-neutral-500">Location: </span>${cam.intersection_name || "Surveillance Point"}</p>
              <p class="text-[11px]"><span class="text-neutral-500">Coordinates: </span>${cam.latitude.toFixed(4)}, ${cam.longitude.toFixed(4)}</p>
              <p class="text-[11px]"><span class="text-neutral-500">Heading: </span>${cam.heading_deg}°</p>
            </div>
          </div>
        `;

        const popup = new maplibregl.Popup({ offset: 16, className: "swiss-maplibre-popup" })
          .setHTML(popupHtml);

        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([cam.longitude, cam.latitude])
          .setPopup(popup)
          .addTo(map);

        cameraMarkersRef.current.push(marker);
      });

      // Fit to camera bounds if no trajectory is active yet
      if (trajectory.points.length === 0) {
        const bounds = new maplibregl.LngLatBounds();
        cameras.forEach((c) => bounds.extend([c.longitude, c.latitude]));
        map.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 600 });
      }
    }
  }, [cameras, showCameras, isMapReady, trajectory.points.length]);

  // 4. Update Trajectory Polylines (GeoJSON line layer)
  const updateTrajectoryPolylines = useCallback(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    ensureTrajectoryLayers(map);

    const features = trajectory.segments.map((seg) => ({
      type: "Feature",
      properties: {
        id: seg.id,
        speed: seg.speed,
        color: seg.color,
      },
      geometry: {
        type: "LineString",
        coordinates: [
          [seg.coordinates[0][1], seg.coordinates[0][0]], // [lng, lat]
          [seg.coordinates[1][1], seg.coordinates[1][0]], // [lng, lat]
        ],
      },
    }));

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

  // 5. Update Chronological Numbered Markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    // Clear existing numbered markers
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

  // 6. Highlight active marker on slider change
  useEffect(() => {
    trajectoryMarkersRef.current.forEach(({ el, index }) => {
      if (index === sliderIndex) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });
  }, [sliderIndex]);

  // 7. Vehicle Animated Cursor Marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isMapReady) return;

    const currentPoint = trajectory.points[sliderIndex] || null;

    if (currentPoint) {
      if (!vehicleCursorRef.current) {
        const el = document.createElement("div");
        el.className = "swiss-vehicle-cursor";
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([currentPoint.lng, currentPoint.lat])
          .addTo(map);
        vehicleCursorRef.current = marker;
      } else {
        vehicleCursorRef.current.setLngLat([currentPoint.lng, currentPoint.lat]);
      }
    } else {
      if (vehicleCursorRef.current) {
        vehicleCursorRef.current.remove();
        vehicleCursorRef.current = null;
      }
    }
  }, [sliderIndex, trajectory.points, isMapReady]);

  // 8. Update slider bounds when points change
  useEffect(() => {
    if (trajectory.points.length > 0) {
      setSliderIndex(trajectory.points.length - 1);
    } else {
      setSliderIndex(0);
    }
  }, [trajectory.points.length]);

  // 9. Timeline Animation Interval
  useEffect(() => {
    if (isPlaying && trajectory.points.length > 1) {
      playIntervalRef.current = setInterval(() => {
        setSliderIndex((prev) => {
          if (prev >= trajectory.points.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 1200 / playbackSpeed);
    } else {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    }

    return () => {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    };
  }, [isPlaying, trajectory.points.length, playbackSpeed]);

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
        {/* MapLibre GL Container with OpenFreeMap Liberty style */}
        <div className="flex-1 relative z-0">
          <div ref={mapContainerRef} className="w-full h-full relative" />
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
