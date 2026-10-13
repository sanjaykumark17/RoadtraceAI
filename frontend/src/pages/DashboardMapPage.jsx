import React, { useState, useEffect, useRef, useMemo } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Polyline,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import apiClient from "../api/client";
import { useTrajectory, getSpeedColor } from "../hooks/useTrajectory";
import { useWebSocket } from "../hooks/useWebSocket";
import {
  Search,
  Play,
  Pause,
  RotateCcw,
  Radio,
  Camera as CameraIcon,
  Activity,
  Layers,
  Clock,
  Gauge,
  Percent,
  Image as ImageIcon,
  ChevronRight,
  Info,
} from "lucide-react";

// Custom Leaflet Icons using Swiss styling
function createNumberedIcon(num, isActive = false) {
  return L.divIcon({
    className: `swiss-marker ${isActive ? "active" : ""}`,
    html: `<span>${num}</span>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -16],
  });
}

function createCameraIcon(name) {
  return L.divIcon({
    className: "swiss-camera-marker",
    html: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
    popupAnchor: [0, -14],
  });
}

function createVehicleCursorIcon() {
  return L.divIcon({
    className: "swiss-vehicle-cursor",
    html: `<div></div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

// Controller to smoothly fit map bounds
function MapBoundsUpdater({ points, cameras }) {
  const map = useMap();

  useEffect(() => {
    if (points && points.length > 0) {
      const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lng]));
      map.fitBounds(bounds, { padding: [60, 60], maxZoom: 15 });
    } else if (cameras && cameras.length > 0) {
      const bounds = L.latLngBounds(cameras.map((c) => [c.latitude, c.longitude]));
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 13 });
    }
  }, [points, cameras, map]);

  return null;
}

export function DashboardMapPage({ initialSearchPlate = null, onPlateSelect = null }) {
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

  // Fetch cameras and sample plates
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

  // Update slider bounds when points change
  useEffect(() => {
    if (trajectory.points.length > 0) {
      setSliderIndex(trajectory.points.length - 1);
    } else {
      setSliderIndex(0);
    }
  }, [trajectory.points.length]);

  // Handle timeline animation
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

  // Center around Chennai corridor (Kathipara to ORR)
  const defaultCenter = [12.9675, 80.1491];

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
        {/* Leaflet Map Container */}
        <div className="flex-1 relative z-0">
          <MapContainer
            center={defaultCenter}
            zoom={12}
            className="w-full h-full"
            zoomControl={false}
          >
            {/* Dark Swiss Map Tiles */}
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />

            <MapBoundsUpdater points={trajectory.points} cameras={cameras} />

            {/* Cameras Layer */}
            {showCameras &&
              cameras.map((cam) => (
                <Marker
                  key={`cam-${cam.id}`}
                  position={[cam.latitude, cam.longitude]}
                  icon={createCameraIcon(cam.name)}
                >
                  <Popup>
                    <div className="p-3 font-mono text-xs max-w-xs">
                      <div className="font-bold text-white text-sm border-b border-neutral-800 pb-1 mb-2 flex items-center justify-between">
                        <span>{cam.name}</span>
                        <span className="text-[10px] text-emerald-400 uppercase bg-emerald-950/60 px-1 rounded">
                          {cam.status}
                        </span>
                      </div>
                      <div className="space-y-1 text-neutral-300">
                        <p className="text-[11px]">
                          <span className="text-neutral-500">Location: </span>
                          {cam.intersection_name || "Surveillance Point"}
                        </p>
                        <p className="text-[11px]">
                          <span className="text-neutral-500">Coordinates: </span>
                          {cam.latitude.toFixed(4)}, {cam.longitude.toFixed(4)}
                        </p>
                        <p className="text-[11px]">
                          <span className="text-neutral-500">Heading: </span>
                          {cam.heading_deg}°
                        </p>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}

            {/* Color-Coded Trajectory Segments */}
            {trajectory.segments.map((seg) => (
              <Polyline
                key={seg.id}
                positions={seg.coordinates}
                pathOptions={{
                  color: seg.color,
                  weight: 5,
                  opacity: 0.9,
                  lineJoin: "round",
                }}
              />
            ))}

            {/* Chronological Numbered Markers */}
            {trajectory.points.map((pt, idx) => {
              const isSelected = sliderIndex === idx;

              return (
                <Marker
                  key={pt.id}
                  position={[pt.lat, pt.lng]}
                  icon={createNumberedIcon(pt.markerIndex, isSelected)}
                >
                  <Popup>
                    <div className="p-3 font-mono text-xs w-64 bg-neutral-900 rounded">
                      <div className="flex items-center justify-between border-b border-neutral-800 pb-1 mb-2">
                        <span className="font-bold text-white text-sm">
                          Marker #{pt.markerIndex}
                        </span>
                        <span className="text-[11px] font-semibold text-neutral-300 bg-neutral-800 px-1.5 py-0.5 rounded">
                          {pt.plate}
                        </span>
                      </div>

                      <div className="space-y-1.5 text-neutral-300 text-[11px]">
                        <div className="flex justify-between">
                          <span className="text-neutral-500">Camera:</span>
                          <span className="text-white font-semibold">{pt.cameraName}</span>
                        </div>

                        <div className="flex justify-between">
                          <span className="text-neutral-500">Timestamp:</span>
                          <span className="text-neutral-200">
                            {new Date(pt.timestamp).toLocaleTimeString()}
                          </span>
                        </div>

                        <div className="flex justify-between">
                          <span className="text-neutral-500">Dwell Time:</span>
                          <span className="text-neutral-200">
                            {pt.dwellSeconds !== null && pt.dwellSeconds !== undefined
                              ? `${Math.round(pt.dwellSeconds)}s`
                              : "Terminal / Active"}
                          </span>
                        </div>

                        <div className="flex justify-between">
                          <span className="text-neutral-500">Est. Speed:</span>
                          <span
                            className="font-bold"
                            style={{ color: getSpeedColor(pt.estimatedSpeed) }}
                          >
                            {pt.estimatedSpeed !== null
                              ? `${pt.estimatedSpeed} km/h`
                              : "Origin Point"}
                          </span>
                        </div>

                        <div className="flex justify-between">
                          <span className="text-neutral-500">OCR Conf:</span>
                          <span className="text-emerald-400 font-semibold">
                            {pt.ocrConfidence !== null
                              ? `${Math.round(pt.ocrConfidence * 100)}%`
                              : "99%"}
                          </span>
                        </div>
                      </div>

                      {/* Snapshot Image Preview */}
                      {pt.snapshotUrl ? (
                        <div className="mt-3 border border-neutral-800 rounded overflow-hidden">
                          <img
                            src={pt.snapshotUrl}
                            alt={`Plate ${pt.plate} snapshot`}
                            className="w-full h-24 object-cover bg-neutral-950"
                            onError={(e) => {
                              e.target.style.display = "none";
                            }}
                          />
                        </div>
                      ) : (
                        <div className="mt-2.5 p-2 bg-neutral-950 border border-neutral-800 rounded flex items-center justify-center space-x-1 text-neutral-500 text-[10px]">
                          <ImageIcon className="w-3 h-3" />
                          <span>Snapshot captured in DB</span>
                        </div>
                      )}
                    </div>
                  </Popup>
                </Marker>
              );
            })}

            {/* Vehicle Animated Cursor */}
            {currentPoint && (
              <Marker
                position={[currentPoint.lat, currentPoint.lng]}
                icon={createVehicleCursorIcon()}
                zIndexOffset={1200}
              />
            )}
          </MapContainer>
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
