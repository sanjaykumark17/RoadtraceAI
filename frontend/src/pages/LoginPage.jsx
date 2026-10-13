import React, { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { Shield, KeyRound, ArrowRight, AlertCircle, CheckCircle2 } from "lucide-react";

export function LoginPage() {
  const { login, loading } = useAuth();
  const [email, setEmail] = useState("admin@roadtrace.ai");
  const [password, setPassword] = useState("admin123");
  const [error, setError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    const res = await login(email, password);
    if (!res.success) {
      setError(res.error);
    }
  };

  const handleDemoFill = (demoEmail, demoPass) => {
    setEmail(demoEmail);
    setPassword(demoPass);
    setError(null);
  };

  return (
    <div className="min-h-screen bg-neutral-950 flex flex-col justify-center py-12 px-4 sm:px-6 lg:px-8">
      {/* Swiss grid accent line */}
      <div className="absolute inset-0 bg-[linear-gradient(to_right,#1f1f1f_1px,transparent_1px),linear-gradient(to_bottom,#1f1f1f_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] opacity-30 pointer-events-none" />

      <div className="sm:mx-auto sm:w-full sm:max-w-md relative z-10">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-lg bg-neutral-900 border border-neutral-700 shadow-inner">
            <span className="font-mono text-xl font-bold tracking-tighter text-white">RT</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-white uppercase font-sans">
            ROADTRACE AI
          </h1>
          <p className="text-xs font-mono uppercase tracking-widest text-neutral-400">
            Multi-Camera Vehicle Surveillance & ANPR Trajectory Reconstruction
          </p>
        </div>

        {/* Card Form */}
        <div className="mt-8 bg-neutral-900/90 border border-neutral-800 p-8 rounded-lg shadow-2xl backdrop-blur-sm">
          {error && (
            <div className="mb-6 p-3 bg-red-950/40 border border-red-800/80 rounded flex items-start space-x-2 text-red-300 text-xs">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-red-400" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-mono uppercase tracking-wider text-neutral-300 mb-1.5">
                Operator Email
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operator@roadtrace.ai"
                className="w-full px-3.5 py-2.5 bg-neutral-950 border border-neutral-700 rounded text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-white focus:ring-1 focus:ring-white transition font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-mono uppercase tracking-wider text-neutral-300 mb-1.5">
                Passphrase
              </label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                className="w-full px-3.5 py-2.5 bg-neutral-950 border border-neutral-700 rounded text-sm text-white placeholder-neutral-500 focus:outline-none focus:border-white focus:ring-1 focus:ring-white transition font-mono"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full mt-2 py-3 px-4 bg-white hover:bg-neutral-200 text-black font-semibold text-xs uppercase tracking-wider rounded transition flex items-center justify-center space-x-2 disabled:opacity-50"
            >
              {loading ? (
                <span>Authenticating JWT...</span>
              ) : (
                <>
                  <span>Authenticate Session</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Seeded Roles Quick Selector */}
          <div className="mt-8 pt-6 border-t border-neutral-800">
            <p className="text-[11px] font-mono uppercase tracking-wider text-neutral-400 text-center mb-3">
              Seeded Verification Accounts:
            </p>
            <div className="grid grid-cols-3 gap-2">
              <button
                type="button"
                onClick={() => handleDemoFill("admin@roadtrace.ai", "admin123")}
                className="px-2 py-1.5 bg-neutral-950 hover:bg-neutral-800 border border-neutral-800 rounded text-[11px] font-mono text-neutral-200 transition text-center"
              >
                <div className="font-semibold text-white">Admin</div>
                <div className="text-[9px] text-neutral-400">Full Access</div>
              </button>
              <button
                type="button"
                onClick={() => handleDemoFill("operator@roadtrace.ai", "operator123")}
                className="px-2 py-1.5 bg-neutral-950 hover:bg-neutral-800 border border-neutral-800 rounded text-[11px] font-mono text-neutral-200 transition text-center"
              >
                <div className="font-semibold text-white">Operator</div>
                <div className="text-[9px] text-neutral-400">Trace & Jobs</div>
              </button>
              <button
                type="button"
                onClick={() => handleDemoFill("viewer@roadtrace.ai", "viewer123")}
                className="px-2 py-1.5 bg-neutral-950 hover:bg-neutral-800 border border-neutral-800 rounded text-[11px] font-mono text-neutral-200 transition text-center"
              >
                <div className="font-semibold text-white">Viewer</div>
                <div className="text-[9px] text-neutral-400">Read-Only</div>
              </button>
            </div>
          </div>
        </div>

        <p className="text-center text-[11px] font-mono text-neutral-400 mt-6">
          Access Token: 15 min · Refresh Token: 7 days · Automatic Token Rotation
        </p>
      </div>
    </div>
  );
}

export default LoginPage;
