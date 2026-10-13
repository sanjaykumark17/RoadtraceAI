import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { AuthProvider, parseJwt } from "../context/AuthContext";
import { useAuth } from "../hooks/useAuth";
import apiClient from "../api/client";

vi.mock("../api/client", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

// Helper to create a fake JWT with standard payload
function createMockJwt(userId, role, expOffsetSec = 900) {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const exp = Math.floor(Date.now() / 1000) + expOffsetSec;
  const payload = btoa(JSON.stringify({ sub: String(userId), role, type: "access", exp }));
  return `${header}.${payload}.mocksignature`;
}

describe("useAuth & AuthContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("parseJwt correctly extracts payload from valid JWT", () => {
    const token = createMockJwt(1, "admin");
    const payload = parseJwt(token);
    expect(payload).not.toBeNull();
    expect(payload.sub).toBe("1");
    expect(payload.role).toBe("admin");
  });

  it("parseJwt returns null for invalid token strings", () => {
    expect(parseJwt("invalid.token")).toBeNull();
    expect(parseJwt(null)).toBeNull();
    expect(parseJwt("")).toBeNull();
  });

  it("initializes with unauthenticated state when localStorage is empty", () => {
    const wrapper = ({ children }) => <AuthProvider>{children}</AuthProvider>;
    const { result } = renderHook(() => useAuth(), { wrapper });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
    expect(result.current.role).toBe("viewer");
  });

  it("authenticates user and saves tokens on successful login", async () => {
    const mockAccess = createMockJwt(42, "operator");
    const mockRefresh = "mock-refresh-token";

    apiClient.post.mockResolvedValueOnce({
      data: {
        access_token: mockAccess,
        refresh_token: mockRefresh,
      },
    });
    apiClient.get.mockResolvedValueOnce({
      data: { id: 42, email: "operator@roadtrace.ai", role: "operator" },
    });

    const wrapper = ({ children }) => <AuthProvider>{children}</AuthProvider>;
    const { result } = renderHook(() => useAuth(), { wrapper });

    let loginRes;
    await act(async () => {
      loginRes = await result.current.login("operator@roadtrace.ai", "operator123");
    });

    expect(loginRes.success).toBe(true);
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.role).toBe("operator");
    expect(result.current.isOperator).toBe(true);
    expect(result.current.isAdmin).toBe(false);

    expect(localStorage.getItem("roadtrace_access_token")).toBe(mockAccess);
    expect(localStorage.getItem("roadtrace_refresh_token")).toBe(mockRefresh);
  });

  it("clears state and removes tokens on logout", async () => {
    localStorage.setItem("roadtrace_access_token", createMockJwt(1, "admin"));
    localStorage.setItem("roadtrace_refresh_token", "ref123");

    const wrapper = ({ children }) => <AuthProvider>{children}</AuthProvider>;
    const { result } = renderHook(() => useAuth(), { wrapper });

    act(() => {
      result.current.logout();
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
    expect(localStorage.getItem("roadtrace_access_token")).toBeNull();
    expect(localStorage.getItem("roadtrace_refresh_token")).toBeNull();
  });
});
