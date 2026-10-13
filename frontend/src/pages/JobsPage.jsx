import React, { useState, useEffect } from "react";
import apiClient from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { Cpu, Upload, RefreshCw, AlertCircle, CheckCircle2, Clock, Film } from "lucide-react";
import { LoadingSpinner, EmptyState, ErrorState } from "../components/States";
import RoleGuard from "../components/RoleGuard";

export function JobsPage() {
  const { isOperator, isAdmin, role } = useAuth();
  const [jobs, setJobs] = useState([]);
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Upload / Trigger Form State
  const [selectedCameraId, setSelectedCameraId] = useState("");
  const [sourceUri, setSourceUri] = useState("");
  const [videoFile, setVideoFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [successMessage, setSuccessMessage] = useState(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [jobsRes, camsRes] = await Promise.allSettled([
        apiClient.get("/jobs"),
        apiClient.get("/cameras"),
      ]);

      if (jobsRes.status === "fulfilled") {
        setJobs(jobsRes.value.data || []);
      }
      if (camsRes.status === "fulfilled") {
        const camList = camsRes.value.data || [];
        setCameras(camList);
        if (camList.length > 0 && !selectedCameraId) {
          setSelectedCameraId(String(camList[0].id));
        }
      }
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load jobs pipeline");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(() => {
      // Periodic background refresh for running jobs
      apiClient.get("/jobs").then((res) => setJobs(res.data || [])).catch(() => {});
    }, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleCreateJob = async (e) => {
    e.preventDefault();
    if (!selectedCameraId) {
      alert("Please select a camera node");
      return;
    }

    setSubmitting(true);
    setError(null);
    setSuccessMessage(null);

    try {
      if (videoFile) {
        // Send multipart form with file
        const formData = new FormData();
        formData.append("camera_id", selectedCameraId);
        formData.append("video", videoFile);
        formData.append("source_uri", `upload://${videoFile.name}`);

        const res = await apiClient.post("/jobs", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        setJobs((prev) => [res.data, ...prev]);
      } else {
        // Send JSON with source_uri
        const res = await apiClient.post("/jobs", {
          camera_id: parseInt(selectedCameraId, 10),
          source_uri: sourceUri || "rtsp://camera.internal/live.mp4",
        });
        setJobs((prev) => [res.data, ...prev]);
      }

      setSuccessMessage("Inference job queued successfully into processing pipeline.");
      setSourceUri("");
      setVideoFile(null);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to submit processing job");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 font-sans">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white uppercase font-mono">
            Video Processing & ANPR Jobs
          </h1>
          <p className="text-xs font-mono text-neutral-400 mt-1">
            YOLOv8 vehicle detection + EasyOCR character voting pipeline execution
          </p>
        </div>

        <button
          onClick={loadData}
          className="px-3 py-1.5 bg-neutral-900 hover:bg-neutral-800 text-neutral-300 border border-neutral-700 rounded text-xs font-mono uppercase tracking-wider flex items-center space-x-1.5 transition"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh Queue</span>
        </button>
      </div>

      {error && <ErrorState title="Pipeline Error" error={error} onRetry={loadData} />}
      {successMessage && (
        <div className="mb-6 p-3 bg-emerald-950/40 border border-emerald-800 rounded flex items-center space-x-2 text-emerald-300 text-xs font-mono">
          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Upload & Trigger Card (Operator / Admin) */}
      <RoleGuard
        requiredRole="operator"
        fallback={
          <div className="mb-6 p-4 border border-neutral-800 bg-neutral-900/60 rounded text-xs font-mono text-neutral-400">
            Viewer Mode: You can monitor ongoing processing jobs below. Submitting new inference jobs requires operator access.
          </div>
        }
      >
        <div className="border border-neutral-800 bg-neutral-900 p-6 rounded-lg mb-8 shadow-sm">
          <h2 className="text-xs font-mono uppercase tracking-widest text-neutral-300 mb-4 flex items-center space-x-2">
            <Film className="w-4 h-4 text-white" />
            <span>Enqueue Video Stream or File for ANPR Extraction</span>
          </h2>

          <form onSubmit={handleCreateJob} className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
            <div>
              <label className="block text-neutral-400 uppercase mb-1.5">Associated Camera</label>
              <select
                required
                value={selectedCameraId}
                onChange={(e) => setSelectedCameraId(e.target.value)}
                className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
              >
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.intersection_name || "Corridor"})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-neutral-400 uppercase mb-1.5">Upload MP4 Video</label>
              <input
                type="file"
                accept="video/*"
                onChange={(e) => setVideoFile(e.target.files?.[0] || null)}
                className="w-full px-2 py-1.5 bg-neutral-950 border border-neutral-700 rounded text-neutral-300 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:text-[11px] file:bg-neutral-800 file:text-white"
              />
            </div>

            <div>
              <label className="block text-neutral-400 uppercase mb-1.5">Or Source URI (RTSP / File)</label>
              <div className="flex space-x-2">
                <input
                  type="text"
                  value={sourceUri}
                  onChange={(e) => setSourceUri(e.target.value)}
                  placeholder="rtsp://feed/stream.mp4 or sample.mp4"
                  className="flex-1 px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
                />
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 bg-white hover:bg-neutral-200 text-black font-bold uppercase rounded tracking-wider transition disabled:opacity-50"
                >
                  {submitting ? "Queuing..." : "Start"}
                </button>
              </div>
            </div>
          </form>
        </div>
      </RoleGuard>

      {/* Jobs Monitoring Queue */}
      <div className="border border-neutral-800 bg-neutral-900 rounded-lg overflow-hidden shadow">
        <div className="px-4 py-3 border-b border-neutral-800 bg-neutral-950/70 flex items-center justify-between text-xs font-mono">
          <span className="text-neutral-400 uppercase">
            Inference Pipeline Jobs: <strong className="text-white">{jobs.length}</strong>
          </span>
          <span className="text-neutral-500 text-[11px]">AUTO-REFRESHING EVERY 5S</span>
        </div>

        {jobs.length === 0 ? (
          <div className="p-8 text-center font-mono text-xs text-neutral-500">
            No active or past video processing jobs found.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead className="bg-neutral-950 text-neutral-400 uppercase tracking-wider text-[11px] border-b border-neutral-800">
                <tr>
                  <th className="px-4 py-3">Job ID</th>
                  <th className="px-4 py-3">Camera Node</th>
                  <th className="px-4 py-3">Video Source</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-center">Frames Processed</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Finished</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60">
                {jobs.map((job) => {
                  const cam = cameras.find((c) => c.id === job.camera_id);
                  return (
                    <tr key={job.id} className="hover:bg-neutral-800/30 transition">
                      <td className="px-4 py-3 font-bold text-white">#{job.id}</td>
                      <td className="px-4 py-3 text-neutral-300">
                        {cam ? `${cam.name}` : `Camera #${job.camera_id}`}
                      </td>
                      <td className="px-4 py-3 text-neutral-400 max-w-xs truncate">
                        {job.source_uri}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] uppercase font-semibold ${
                            job.status === "done"
                              ? "bg-emerald-950 text-emerald-400 border border-emerald-800/60"
                              : job.status === "processing"
                              ? "bg-amber-950 text-amber-400 border border-amber-800/60 animate-pulse"
                              : job.status === "failed"
                              ? "bg-red-950 text-red-400 border border-red-800/60"
                              : "bg-neutral-950 text-neutral-400 border border-neutral-800"
                          }`}
                        >
                          {job.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center font-bold text-neutral-200">
                        {job.frames_processed}
                      </td>
                      <td className="px-4 py-3 text-neutral-400 text-[11px]">
                        {job.started_at ? new Date(job.started_at).toLocaleTimeString() : "—"}
                      </td>
                      <td className="px-4 py-3 text-neutral-400 text-[11px]">
                        {job.finished_at ? new Date(job.finished_at).toLocaleTimeString() : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default JobsPage;
