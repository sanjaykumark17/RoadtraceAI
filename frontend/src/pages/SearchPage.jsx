import React, { useState, useEffect } from "react";
import apiClient from "../api/client";
import { Search, MapPin, Filter, Calendar, Tag, ShieldCheck, ArrowUpRight } from "lucide-react";
import { LoadingSpinner, EmptyState, ErrorState } from "../components/States";

export function SearchPage({ onTracePlate }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);

  // Time filters
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");

  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    setHasSearched(true);

    try {
      const response = await apiClient.get("/search", {
        params: {
          plate: query.trim().toUpperCase(),
        },
      });

      const list = response.data?.results || response.data?.matches || [];
      setResults(list);
    } catch (err) {
      setError(err.response?.data?.detail || "Plate search query failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 font-sans">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-bold tracking-tight text-white uppercase font-mono">
          Vehicle Plate Search & Fuzzy Trace
        </h1>
        <p className="text-xs font-mono text-neutral-400 mt-1">
          Sub-second ANPR database search with Levenshtein fuzzy distance tolerance (≤ 2 edits)
        </p>
      </div>

      {/* Query Bar */}
      <div className="bg-neutral-900 border border-neutral-800 p-4 rounded-lg mb-6 shadow-sm">
        <form onSubmit={handleSearch} className="flex flex-col md:flex-row gap-3">
          <div className="flex-1 relative">
            <Search className="w-4 h-4 text-neutral-500 absolute left-3 top-3" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="ENTER EXACT OR APPROXIMATE LICENSE PLATE (e.g. TN01TJ, KA01...)"
              className="w-full pl-9 pr-3 py-2 bg-neutral-950 border border-neutral-700 rounded text-sm text-white placeholder-neutral-500 font-mono uppercase focus:outline-none focus:border-white focus:ring-1 focus:ring-white transition"
            />
          </div>

          <div className="flex items-center space-x-2">
            <input
              type="datetime-local"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="px-2.5 py-2 bg-neutral-950 border border-neutral-700 rounded text-xs text-neutral-300 font-mono focus:outline-none"
              title="Filter from timestamp"
            />
            <span className="text-neutral-500 text-xs">to</span>
            <input
              type="datetime-local"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="px-2.5 py-2 bg-neutral-950 border border-neutral-700 rounded text-xs text-neutral-300 font-mono focus:outline-none"
              title="Filter to timestamp"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="px-5 py-2 bg-white hover:bg-neutral-200 text-black font-semibold text-xs uppercase tracking-wider rounded transition flex items-center justify-center space-x-1 font-mono disabled:opacity-50"
          >
            <span>Query ANPR</span>
          </button>
        </form>
      </div>

      {/* Feedback States */}
      {error && <ErrorState title="Search Failed" error={error} onRetry={handleSearch} />}
      {loading && <LoadingSpinner text="Querying license plate indices & fuzzy match candidates..." />}

      {/* Results Table */}
      {!loading && !error && hasSearched && results.length === 0 && (
        <EmptyState
          title="No Vehicle Matches Found"
          description={`No recorded vehicles found within distance <= 2 for query "${query.toUpperCase()}". Check plate characters or try a prefix search.`}
          icon={Search}
        />
      )}

      {!loading && results.length > 0 && (
        <div className="border border-neutral-800 bg-neutral-900 rounded-lg overflow-hidden shadow">
          <div className="px-4 py-3 border-b border-neutral-800 bg-neutral-950/70 flex items-center justify-between text-xs font-mono">
            <span className="text-neutral-400">
              CANDIDATES FOUND: <strong className="text-white">{results.length}</strong>
            </span>
            <span className="text-neutral-500 text-[11px]">
              ORDERED BY LEVENSHTEIN DISTANCE & FREQUENCY
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left font-mono text-xs">
              <thead className="bg-neutral-950 text-neutral-400 uppercase tracking-wider text-[11px] border-b border-neutral-800">
                <tr>
                  <th className="px-4 py-3">License Plate</th>
                  <th className="px-4 py-3">Classification</th>
                  <th className="px-4 py-3 text-center">Fuzzy Distance</th>
                  <th className="px-4 py-3 text-center">Total Sightings</th>
                  <th className="px-4 py-3">First Seen</th>
                  <th className="px-4 py-3">Last Seen</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60">
                {results.map((item) => (
                  <tr key={item.plate_number} className="hover:bg-neutral-800/40 transition">
                    <td className="px-4 py-3 font-bold text-white flex items-center space-x-2">
                      <span className="px-2 py-0.5 bg-neutral-950 border border-neutral-700 rounded text-xs text-neutral-200">
                        {item.plate_number}
                      </span>
                      {item.is_exact && (
                        <span className="text-[9px] bg-emerald-950 text-emerald-400 border border-emerald-800/80 px-1 py-0.2 rounded font-sans uppercase">
                          Exact
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-neutral-300">
                      {item.vehicle_class || "Passenger Car"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[11px] ${
                          item.distance === 0
                            ? "bg-neutral-800 text-white font-bold"
                            : "bg-neutral-900 text-neutral-400"
                        }`}
                      >
                        {item.distance === 0 ? "0 (Match)" : `+${item.distance}`}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center font-bold text-neutral-200">
                      {item.sighting_count || 1}
                    </td>
                    <td className="px-4 py-3 text-neutral-400 text-[11px]">
                      {item.first_seen ? new Date(item.first_seen).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-3 text-neutral-400 text-[11px]">
                      {item.last_seen ? new Date(item.last_seen).toLocaleString() : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => onTracePlate(item.plate_number)}
                        className="inline-flex items-center space-x-1 px-3 py-1 bg-white hover:bg-neutral-200 text-black font-semibold text-[11px] rounded transition shadow-sm"
                      >
                        <span>Reconstruct Route</span>
                        <ArrowUpRight className="w-3 h-3" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default SearchPage;
