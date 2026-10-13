import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "../hooks/useWebSocket";

// Mock WebSocket class
class MockWebSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    MockWebSocket.instances.push(this);

    // Simulate async open
    setTimeout(() => {
      this.readyState = 1; // OPEN
      if (this.onopen) this.onopen();
    }, 10);
  }

  send(data) {
    this.lastSent = data;
  }

  close() {
    this.readyState = 3; // CLOSED
    if (this.onclose) this.onclose({ wasClean: true });
  }

  // Test helper to simulate incoming message
  triggerMessage(data) {
    if (this.onmessage) {
      this.onmessage({ data: JSON.stringify(data) });
    }
  }

  triggerError() {
    if (this.onerror) {
      this.onerror(new Error("WS error"));
    }
  }
}

describe("useWebSocket hook", () => {
  let originalWebSocket;

  beforeEach(() => {
    originalWebSocket = global.WebSocket;
    MockWebSocket.instances = [];
    global.WebSocket = MockWebSocket;
  });

  afterEach(() => {
    global.WebSocket = originalWebSocket;
  });

  it("remains disconnected when plate is null", () => {
    const { result } = renderHook(() => useWebSocket(null));
    expect(result.current.status).toBe("disconnected");
    expect(result.current.isConnected).toBe(false);
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it("connects to websocket and transitions to connected state", async () => {
    const { result } = renderHook(() => useWebSocket("TN01TJ1234"));

    expect(result.current.status).toBe("connecting");
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0].url).toContain("/ws/trajectory/TN01TJ1234");

    // Wait for onopen
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(result.current.status).toBe("connected");
    expect(result.current.isConnected).toBe(true);
  });

  it("dispatches incoming messages to callback and updates lastMessage", async () => {
    const onMessageMock = vi.fn();
    const { result } = renderHook(() => useWebSocket("TN01TJ1234", onMessageMock));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    const mockSighting = {
      type: "Feature",
      geometry: { type: "Point", coordinates: [80.203, 13.0067] },
      properties: {
        plate: "TN01TJ1234",
        camera_name: "CAM-01",
        timestamp: "2026-10-10T12:00:00Z",
      },
    };

    act(() => {
      MockWebSocket.instances[0].triggerMessage(mockSighting);
    });

    expect(onMessageMock).toHaveBeenCalledWith(mockSighting);
    expect(result.current.lastMessage).toEqual(mockSighting);
  });
});
