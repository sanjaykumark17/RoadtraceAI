import React, { useState, useEffect } from "react";
import apiClient from "../api/client";
import { useAuth } from "../hooks/useAuth";
import { AlertTriangle, Plus, Trash2, CheckCircle2, ShieldAlert, X } from "lucide-react";
import { LoadingSpinner, EmptyState, ErrorState } from "../components/States";
import RoleGuard from "../components/RoleGuard";

export function AlertsPage() {
  const { isOperator, role } = useAuth();
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [plateNumber, setPlateNumber] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadAlerts = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get("/alerts");
      setAlerts(res.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to load active alert hotlist");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAlerts();
  }, []);

  const handleCreateAlert = async (e) => {
    e.preventDefault();
    if (!plateNumber.trim() || !reason.trim()) return;

    setSubmitting(true);
    try {
      const res = await apiClient.post("/alerts", {
        plate_number: plateNumber.trim().toUpperCase(),
        reason: reason.trim(),
      });
      setAlerts((prev) => [res.data, ...prev]);
      setPlateNumber("");
      setReason("");
      setIsModalOpen(false);
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to create alert entry");
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleActive = async (alertItem) => {
    try {
      const res = await apiClient.put(`/alerts/${alertItem.id}`, {
        is_active: !alertItem.is_active,
      });
      setAlerts((prev) => prev.map((a) => (a.id === alertItem.id ? res.data : a)));
    } catch (err) {
      alert(err.response?.data?.detail || "Failed to update alert state");
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this watch alert?")) return;
    try {
      await apiClient.delete(`/alerts/${id}`);
      setAlerts((prev) => prev.filter((a) => a.id !== id));
    } catch (err) {
      alert(err.response?.data?.detail || "Delete alert failed");
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 font-sans">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white uppercase font-mono">
            Surveillance BOLO & Hotlist Alerts
          </h1>
          <p className="text-xs font-mono text-neutral-400 mt-1">
            Real-time interception triggers for flagged license plates
          </p>
        </div>

        {isOperator ? (
          <button
            onClick={() => setIsModalOpen(true)}
            className="px-4 py-2 bg-white hover:bg-neutral-200 text-black font-semibold text-xs uppercase tracking-wider rounded transition flex items-center space-x-2 font-mono shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Create BOLO Alert</span>
          </button>
        ) : (
          <div className="px-3 py-1.5 bg-neutral-900 border border-neutral-800 rounded text-neutral-400 text-xs font-mono">
            Viewer Mode (Read-Only)
          </div>
        )}
      </div>

      {error && <ErrorState title="Alert Feed Error" error={error} onRetry={loadAlerts} />}
      {loading && <LoadingSpinner text="Retrieving surveillance hotlist entries..." />}

      {/* Alerts Table */}
      {!loading && (
        <div className="border border-neutral-800 bg-neutral-900 rounded-lg overflow-hidden shadow">
          {alerts.length === 0 ? (
            <div className="p-8 text-center font-mono text-xs text-neutral-500">
              No surveillance hotlist alerts currently active.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead className="bg-neutral-950 text-neutral-400 uppercase tracking-wider text-[11px] border-b border-neutral-800">
                  <tr>
                    <th className="px-4 py-3">Flagged Plate</th>
                    <th className="px-4 py-3">Interception Reason</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Created</th>
                    {isOperator && <th className="px-4 py-3 text-right">Actions</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-800/60">
                  {alerts.map((al) => (
                    <tr key={al.id} className="hover:bg-neutral-800/30 transition">
                      <td className="px-4 py-3 font-bold text-white flex items-center space-x-2">
                        <AlertTriangle
                          className={`w-4 h-4 shrink-0 ${
                            al.is_active ? "text-amber-400" : "text-neutral-500"
                          }`}
                        />
                        <span className="px-2 py-0.5 bg-neutral-950 border border-neutral-700 rounded text-xs text-neutral-200">
                          {al.plate_number}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-neutral-300">{al.reason}</td>
                      <td className="px-4 py-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] uppercase font-semibold ${
                            al.is_active
                              ? "bg-red-950 text-red-400 border border-red-800/60"
                              : "bg-neutral-950 text-neutral-500 border border-neutral-800"
                          }`}
                        >
                          {al.is_active ? "HOTLIST ACTIVE" : "DEACTIVATED"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-neutral-400 text-[11px]">
                        {al.created_at ? new Date(al.created_at).toLocaleDateString() : "—"}
                      </td>
                      {isOperator && (
                        <td className="px-4 py-3 text-right space-x-2">
                          <button
                            onClick={() => handleToggleActive(al)}
                            className="px-2 py-0.5 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 rounded text-[10px] uppercase transition"
                          >
                            {al.is_active ? "Deactivate" : "Activate"}
                          </button>
                          <button
                            onClick={() => handleDelete(al.id)}
                            className="p-1 hover:text-red-400 text-neutral-400 transition"
                            title="Delete alert"
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
          )}
        </div>
      )}

      {/* Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4 backdrop-blur-xs">
          <div className="bg-neutral-900 border border-neutral-800 rounded-lg max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-neutral-800 mb-4">
              <h3 className="text-sm font-bold uppercase font-mono text-white">
                Register Hotlist BOLO Alert
              </h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-neutral-500 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateAlert} className="space-y-4 font-mono text-xs">
              <div>
                <label className="block text-neutral-400 uppercase mb-1">Target License Plate</label>
                <input
                  type="text"
                  required
                  value={plateNumber}
                  onChange={(e) => setPlateNumber(e.target.value)}
                  placeholder="e.g. TN01TJ7492"
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white uppercase focus:outline-none focus:border-white"
                />
              </div>

              <div>
                <label className="block text-neutral-400 uppercase mb-1">Alert Reason / BOLO Summary</label>
                <textarea
                  required
                  rows={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Stolen vehicle / suspect vehicle flagged for immediate interception."
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-white focus:outline-none focus:border-white"
                />
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
                  disabled={submitting}
                  className="px-4 py-2 bg-white hover:bg-neutral-200 text-black font-bold rounded text-xs uppercase"
                >
                  {submitting ? "Broadcasting..." : "Broadcast Alert"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default AlertsPage;
