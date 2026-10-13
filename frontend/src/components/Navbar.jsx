import React from "react";
import { useAuth } from "../hooks/useAuth";
import { 
  MapPin, 
  Search, 
  Camera, 
  Cpu, 
  AlertTriangle, 
  LogOut, 
  ShieldCheck, 
  Radio 
} from "lucide-react";

export function Navbar({ activeTab, onSelectTab }) {
  const { user, role, logout, isAdmin, isOperator } = useAuth();

  const navItems = [
    { id: "dashboard", label: "Dashboard Map", icon: MapPin },
    { id: "search", label: "Search & Trace", icon: Search },
    { id: "cameras", label: "Cameras", icon: Camera, adminOnly: true },
    { id: "jobs", label: "Jobs", icon: Cpu, operatorOnly: true },
    { id: "alerts", label: "Alerts", icon: AlertTriangle, operatorOnly: true },
  ];

  return (
    <header className="sticky top-0 z-50 bg-neutral-950/95 backdrop-blur border-b border-neutral-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between">
        {/* Brand / Logo */}
        <div className="flex items-center space-x-3 cursor-pointer" onClick={() => onSelectTab("dashboard")}>
          <div className="w-7 h-7 bg-white text-black font-mono font-bold flex items-center justify-center rounded text-sm shadow-sm">
            RT
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="font-bold tracking-tight text-white text-sm">ROADTRACE</span>
              <span className="text-[10px] font-mono uppercase bg-neutral-800 text-neutral-300 px-1.5 py-0.5 rounded border border-neutral-700">
                AI / ANPR
              </span>
            </div>
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav className="hidden md:flex items-center space-x-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            const isDisabled = item.adminOnly && !isAdmin;

            return (
              <button
                key={item.id}
                onClick={() => onSelectTab(item.id)}
                className={`flex items-center space-x-2 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                  isActive
                    ? "bg-neutral-800 text-white shadow-inner border border-neutral-700"
                    : "text-neutral-400 hover:text-white hover:bg-neutral-900"
                } ${isDisabled ? "opacity-60" : ""}`}
              >
                <Icon className={`w-3.5 h-3.5 ${isActive ? "text-white" : "text-neutral-400"}`} />
                <span>{item.label}</span>
                {item.adminOnly && (
                  <span className="text-[9px] font-mono tracking-wider bg-red-950 text-red-300 border border-red-800/60 px-1 rounded">
                    ADMIN
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Right Section: Status Pill & User */}
        <div className="flex items-center space-x-4">
          <div className="hidden sm:flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-emerald-950/40 border border-emerald-800/50 text-emerald-400 text-[11px] font-mono">
            <Radio className="w-3 h-3 animate-pulse text-emerald-400" />
            <span>FEED LIVE</span>
          </div>

          <div className="flex items-center space-x-2 border-l border-neutral-800 pl-4">
            <div className="text-right hidden sm:block">
              <div className="text-xs font-medium text-neutral-200 truncate max-w-[140px]">
                {user?.email || "Surveillance User"}
              </div>
              <div className="flex items-center justify-end space-x-1">
                <ShieldCheck className="w-2.5 h-2.5 text-neutral-400" />
                <span className="text-[10px] font-mono uppercase tracking-wider text-neutral-400">
                  {role}
                </span>
              </div>
            </div>

            <button
              onClick={logout}
              title="Logout session"
              className="p-1.5 text-neutral-400 hover:text-white hover:bg-neutral-900 rounded border border-transparent hover:border-neutral-800 transition"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}

export default Navbar;
