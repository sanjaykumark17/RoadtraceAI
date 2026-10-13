import React, { useState, useEffect } from "react";
import apiClient from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { Camera, Plus, Trash2, Edit2, ShieldAlert, Check, X } from "lucide-react";
import { LoadingSpinner, EmptyState, ErrorState } from "../components/States";
import RoleGuard from "../components/RoleGuard";

export function CamerasPage() {
  const { isAdmin, role } = useAuth();
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Modal / Form state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingCamera, setEditingCamera] = useState(null);
  const [formData, setFormData] = useState({
    name: "",
    latitude: 12.9675,
    longitude: 80.1491,
    intersection_name: "",
    heading_deg: 0.0,
    status: "active",
  });
  const [saving, setSaving] = useState(false);

  const loadCameras = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get("/cameras");
      setCameras(res.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load cameras");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCameras();
  }, []);

  const handleOpenCreate = () => {
    setEditingCamera(null);
    setFormData({
      name: `CAM-GST-${String(cameras.length + 1).padStart(2, "0")}`,
      latitude: 12.936,
      longitude: 80.1305,
      intersection_name: "",
      heading_deg: 180.0,
      status: "active",
    });
    setIsModalOpen(true);
  };

  const handleOpenEdit = (cam) => {
    setEditingCamera(cam);
    setFormData({
      name: cam.name,
      latitude: cam.latitude,
      longitude: cam.longitude,
      intersection_name: cam.intersection_name || "",
      heading_deg: cam.heading_deg || 0,
      status: cam.status || "active",
    });
    setIsModalOpen(true);
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to decommission this surveillance camera?")) return;
    try {
      await apiClient.delete(`/cameras/${id}`);
      setCameras((prev) => prev.filter((c) => c.id !== id));
    } catch (err) {
      alert(err.response?.data?.detail || "Delete operation failed");
    }
  };

  const handleFormSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = {
        name: formData.name,
        latitude: parseFloat(formData.latitude),
        longitude: parseFloat(formData.longitude),
        intersection_name: formData.intersection_name,
        heading_deg: parseFloat(formData.heading_deg),
        status: formData.status,
      };

      if (editingCamera) {
        const res = await apiClient.put(`/cameras/${editingCamera.id}`, payload);
        setCameras((prev) => prev.map((c) => (c.id === editingCamera.id ? res.data : c)));
      } else {
        const res = await apiClient.post("/cameras", payload);
        setCameras((prev) => [...prev, res.data]);
      }
      setIsModalOpen(false);
    } catch (err) {
      alert(err.response?.data?.detail || "Save camera operation failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 font-sans">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="text-xl font-bold tracking-tight text-white uppercase font-mono">
              Surveillance Camera Network
            </h1>
            <span className="text-[10px] font-mono uppercase bg-red-950 text-red-300 border border-red-800/80 px-1.5 py-0.5 rounded">
              ADMIN CONTROL
            </span>
          </div>
          <p className="text-xs font-mono text-neutral-400 mt-1">
            Geo-referenced ANPR optical nodes across the transportation corridor
          </p>
        </div>

        {isAdmin ? (
          <button
            onClick={handleOpenCreate}
            className="px-4 py-2 bg-white hover:bg-neutral-200 text-black font-semibold text-xs uppercase tracking-wider rounded transition flex items-center space-x-2 font-mono shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Register New Camera</span>
          </button>
        ) : (
          <div className="px-3 py-1.5 bg-neutral-900 border border-neutral-800 rounded text-neutral-400 text-xs font-mono">
            Viewer Mode (Read-Only)
          </div>
        )}
      </div>

      {error && <ErrorState title="Camera Feed Error" error={error} onRetry={loadCameras} />}
      {loading && <LoadingSpinner text="Querying registered camera nodes..." />}

      {/* Camera Grid / Table */}
      {!loading && (
        <div className="border border-neutral-800 bg-neutral-900 rounded-lg overflow-hidden shadow">
          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead className="bg-neutral-950 text-neutral-400 uppercase tracking-wider text-[11px] border-b border-neutral-800">
                <tr>
                  <th className="px-4 py-3">Camera Node</th>
                  <th className="px-4 py-3">Intersection / Corridor</th>
                  <th className="px-4 py-3">GPS Coordinates</th>
                  <th className="px-4 py-3">Azimuth / Heading</th>
                  <th className="px-4 py-3">Network Status</th>
                  {isAdmin && <th className="px-4 py-3 text-right">Actions</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60">
                {cameras.map((cam) => (
                  <tr key={cam.id} className="hover:bg-neutral-800/30 transition">
                    <td className="px-4 py-3 font-bold text-white flex items-center space-x-2">
                      <Camera className="w-4 h-4 text-neutral-400 shrink-0" />
                      <span>{cam.name}</span>
                    </td>
                    <td className="px-4 py-3 text-neutral-300">
                      {cam.intersection_name || "Corridor Segment"}
                    </td>
                    <td className="px-4 py-3 text-neutral-400 text-[11px]">
                      {cam.latitude.toFixed(4)}° N, {cam.longitude.toFixed(4)}° E
                    </td>
                    <td className="px-4 py-3 text-neutral-300">
                      {cam.heading_deg}°
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] uppercase font-semibold ${
                          cam.status === "active"
                            ? "bg-emerald-950 text-emerald-400 border border-emerald-800/60"
                            : "bg-neutral-950 text-neutral-400 border border-neutral-800"
                        }`}
                      >
                        {cam.status}
                      </span>
                    </td>
                    {isAdmin && (
                      <td className="px-4 py-3 text-right space-x-2">
                        <button
                          onClick={() => handleOpenEdit(cam)}
                          className="p-1 hover:text-white text-neutral-400 transition"
                          title="Edit camera"
                        >
                          <Edit2 className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleDelete(cam.id)}
                          className="p-1 hover:text-red-400 text-neutral-400 transition"
                          title="Delete camera"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add / Edit Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4 backdrop-blur-xs">
          <div className="bg-neutral-900 border border-neutral-800 rounded-lg max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-neutral-800 mb-4">
              <h3 className="text-sm font-bold uppercase font-mono text-white">
                {editingCamera ? "Edit Camera Configuration" : "Register Optical Node"}
              </h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-neutral-500 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleFormSubmit} className="space-y-4 font-mono text-xs">
              <div>
                <label className="block text-neutral-400 uppercase mb-1">Node Identifier</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="CAM-GST-09"
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
                />
              </div>

              <div>
                <label className="block text-neutral-400 uppercase mb-1">Intersection Name</label>
                <input
                  type="text"
                  value={formData.intersection_name}
                  onChange={(e) => setFormData({ ...formData, intersection_name: e.target.value })}
                  placeholder="Kathipara Urban Interchange"
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-neutral-400 uppercase mb-1">Latitude</label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={formData.latitude}
                    onChange={(e) => setFormData({ ...formData, latitude: e.target.value })}
                    className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
                  />
                </div>
                <div>
                  <label className="block text-neutral-400 uppercase mb-1">Longitude</label>
                  <input
                    type="number"
                    step="any"
                    required
                    value={formData.longitude}
                    onChange={(e) => setFormData({ ...formData, longitude: e.target.value })}
                    className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-neutral-400 uppercase mb-1">Heading (°)</label>
                  <input
                    type="number"
                    step="any"
                    value={formData.heading_deg}
                    onChange={(e) => setFormData({ ...formData, heading_deg: e.target.value })}
                    className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
                  />
                </div>
                <div>
                  <label className="block text-neutral-400 uppercase mb-1">Status</label>
                  <select
                    value={formData.status}
                    onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                    className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
                  >
                    <option value="active">Active</option>
                    <option value="offline">Offline</option>
                    <option value="maintenance">Maintenance</option>
                  </select>
                </div>
              </div>

              <div className="pt-3 border-t border-neutral-800 flex justify-end space-x-2">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-3 py-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 rounded text-xs uppercase"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 bg-white hover:bg-neutral-200 text-black font-bold rounded text-xs uppercase"
                >
                  {saving ? "Saving..." : "Commit Node"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default CamerasPage;
