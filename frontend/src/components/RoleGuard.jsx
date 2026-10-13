import React from "react";
import { useAuth } from "../hooks/useAuth";
import { ShieldAlert } from "lucide-react";

export function RoleGuard({ 
  requiredRole = "admin", 
  children, 
  fallback = null, 
  showNotice = true 
}) {
  const { role, isAdmin, isOperator } = useAuth();

  let hasAccess = false;
  if (requiredRole === "admin") {
    hasAccess = isAdmin;
  } else if (requiredRole === "operator") {
    hasAccess = isOperator;
  } else {
    hasAccess = true;
  }

  if (hasAccess) {
    return <>{children}</>;
  }

  if (fallback) {
    return fallback;
  }

  if (!showNotice) {
    return null;
  }

  return (
    <div className="max-w-xl mx-auto my-12 p-8 border border-neutral-800 bg-neutral-900/60 rounded-lg text-center">
      <div className="w-12 h-12 mx-auto mb-4 bg-red-950/50 border border-red-800/80 rounded-full flex items-center justify-center text-red-400">
        <ShieldAlert className="w-6 h-6" />
      </div>
      <h3 className="text-base font-semibold uppercase tracking-wider text-white">Access Restricted</h3>
      <p className="text-xs text-neutral-400 mt-2 leading-relaxed">
        This surveillance module requires <span className="font-mono text-white font-semibold">{requiredRole.toUpperCase()}</span> permissions.
        Your current session is active as <span className="font-mono text-neutral-300 font-semibold">{role.toUpperCase()}</span> (Read-Only Viewer).
      </p>
      <div className="mt-6 flex justify-center gap-3">
        <span className="text-[11px] font-mono px-3 py-1 bg-neutral-800 text-neutral-400 border border-neutral-700 rounded">
          READ_ONLY_ACCESS_ENFORCED
        </span>
      </div>
    </div>
  );
}

export default RoleGuard;
