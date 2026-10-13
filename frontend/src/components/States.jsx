import React from "react";

export function LoadingSpinner({ text = "Loading surveillance data...", size = "md" }) {
  const sizeClasses = {
    sm: "w-4 h-4 border-2",
    md: "w-8 h-8 border-2",
    lg: "w-12 h-12 border-3",
  };

  return (
    <div className="flex flex-col items-center justify-center p-8 space-y-3" role="status">
      <div
        className={`${sizeClasses[size] || sizeClasses.md} border-neutral-700 border-t-white rounded-full animate-spin`}
      />
      {text && <p className="text-xs font-mono uppercase tracking-widest text-neutral-400">{text}</p>}
      <span className="sr-only">Loading</span>
    </div>
  );
}

export function EmptyState({ title = "No Data Found", description, action, icon: Icon }) {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center border border-neutral-800 bg-neutral-900/50 rounded-lg">
      {Icon && <Icon className="w-10 h-10 text-neutral-500 mb-3" />}
      <h3 className="text-sm font-semibold tracking-wider uppercase text-neutral-200">{title}</h3>
      {description && <p className="text-xs text-neutral-400 mt-1 max-w-sm">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ title = "Operation Failed", error, onRetry }) {
  return (
    <div className="p-4 border border-red-900/50 bg-red-950/20 rounded-md text-left">
      <div className="flex items-start justify-between">
        <div>
          <h4 className="text-xs font-mono uppercase tracking-wider text-red-400 font-semibold">{title}</h4>
          <p className="text-xs text-red-300/80 mt-1">{typeof error === "string" ? error : error?.message || "Unknown error"}</p>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="text-xs uppercase font-mono tracking-wider px-2 py-1 bg-red-900/50 hover:bg-red-800 text-red-200 rounded transition"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
