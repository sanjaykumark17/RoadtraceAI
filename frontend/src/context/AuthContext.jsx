import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import apiClient from "../api/client";

export const AuthContext = createContext(null);

export function parseJwt(token) {
  if (!token || typeof token !== "string") return null;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [accessToken, setAccessToken] = useState(() => localStorage.getItem("roadtrace_access_token"));
  const [refreshToken, setRefreshToken] = useState(() => localStorage.getItem("roadtrace_refresh_token"));
  const [user, setUser] = useState(() => {
    const cached = localStorage.getItem("roadtrace_user");
    if (cached) {
      try {
        return JSON.parse(cached);
      } catch {
        // fallback to token payload
      }
    }
    const token = localStorage.getItem("roadtrace_access_token");
    if (token) {
      const payload = parseJwt(token);
      if (payload) {
        return { id: payload.sub, role: payload.role || "viewer" };
      }
    }
    return null;
  });
  const [loading, setLoading] = useState(false);
  const refreshTimerRef = useRef(null);

  const clearAuth = useCallback(() => {
    localStorage.removeItem("roadtrace_access_token");
    localStorage.removeItem("roadtrace_refresh_token");
    localStorage.removeItem("roadtrace_user");
    setAccessToken(null);
    setRefreshToken(null);
    setUser(null);
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, []);

  const refreshAccessToken = useCallback(async () => {
    const currentRefresh = localStorage.getItem("roadtrace_refresh_token");
    if (!currentRefresh) {
      clearAuth();
      return null;
    }

    try {
      const response = await apiClient.post("/auth/refresh", {
        refresh_token: currentRefresh,
      });
      const { access_token, refresh_token: newRefresh } = response.data;
      localStorage.setItem("roadtrace_access_token", access_token);
      setAccessToken(access_token);

      if (newRefresh) {
        localStorage.setItem("roadtrace_refresh_token", newRefresh);
        setRefreshToken(newRefresh);
      }

      const payload = parseJwt(access_token);
      if (payload) {
        const updatedUser = { id: payload.sub, role: payload.role || "viewer" };
        setUser((prev) => ({ ...(prev || {}), ...updatedUser }));
        localStorage.setItem("roadtrace_user", JSON.stringify(updatedUser));
      }
      return access_token;
    } catch {
      clearAuth();
      return null;
    }
  }, [clearAuth]);

  // Setup auto-refresh timer before token expiration
  const scheduleAutoRefresh = useCallback((token) => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }

    const payload = parseJwt(token);
    if (!payload?.exp) return;

    const expiresInMs = payload.exp * 1000 - Date.now();
    // Refresh 1 minute before expiry, or halfway if lifetime is short
    const refreshDelay = Math.max(1000, expiresInMs - 60000);

    refreshTimerRef.current = setTimeout(() => {
      refreshAccessToken();
    }, refreshDelay);
  }, [refreshAccessToken]);

  useEffect(() => {
    if (accessToken) {
      scheduleAutoRefresh(accessToken);
    }
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, [accessToken, scheduleAutoRefresh]);

  // Listen for auth-expired events from axios interceptor
  useEffect(() => {
    const handleAuthExpired = () => {
      clearAuth();
    };
    window.addEventListener("roadtrace:auth-expired", handleAuthExpired);
    return () => window.removeEventListener("roadtrace:auth-expired", handleAuthExpired);
  }, [clearAuth]);

  const login = async (email, password) => {
    setLoading(true);
    try {
      const response = await apiClient.post("/auth/login", { email, password });
      const { access_token, refresh_token: newRefresh } = response.data;

      localStorage.setItem("roadtrace_access_token", access_token);
      localStorage.setItem("roadtrace_refresh_token", newRefresh);
      setAccessToken(access_token);
      setRefreshToken(newRefresh);

      const payload = parseJwt(access_token);
      const userData = {
        email,
        id: payload?.sub,
        role: payload?.role || "viewer",
      };
      localStorage.setItem("roadtrace_user", JSON.stringify(userData));
      setUser(userData);

      // Attempt to load full /auth/me in background
      try {
        const meRes = await apiClient.get("/auth/me");
        if (meRes.data) {
          const merged = { ...userData, ...meRes.data };
          setUser(merged);
          localStorage.setItem("roadtrace_user", JSON.stringify(merged));
        }
      } catch {
        // fallback to token role
      }

      scheduleAutoRefresh(access_token);
      return { success: true };
    } catch (err) {
      const detail = err.response?.data?.detail || "Login failed. Check your credentials.";
      return { success: false, error: detail };
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    clearAuth();
  };

  const role = user?.role || "viewer";
  const isAuthenticated = Boolean(accessToken);
  const isAdmin = role === "admin";
  const isOperator = role === "operator" || role === "admin";
  const isViewer = role === "viewer";

  return (
    <AuthContext.Provider
      value={{
        user,
        role,
        accessToken,
        refreshToken,
        isAuthenticated,
        isAdmin,
        isOperator,
        isViewer,
        loading,
        login,
        logout,
        refreshAccessToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
