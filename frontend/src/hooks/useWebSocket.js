import { useState, useEffect, useRef, useCallback } from "react";

export function useWebSocket(plate, onMessage) {
  const [status, setStatus] = useState("disconnected"); // 'connecting' | 'connected' | 'disconnected' | 'error'
  const [lastMessage, setLastMessage] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const messageCallbackRef = useRef(onMessage);

  // Keep latest callback reference without triggering re-connections
  useEffect(() => {
    messageCallbackRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
    if (!plate) {
      setStatus("disconnected");
      return;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setStatus("connecting");

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    // Connect through Vite proxy /ws/trajectory/{plate} with access token
    const token = localStorage.getItem("roadtrace_access_token");
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : "";
    const wsUrl = `${protocol}//${host}/ws/trajectory/${encodeURIComponent(plate)}${tokenParam}`;

    try {
      const socket = new WebSocket(wsUrl);
      wsRef.current = socket;

      socket.onopen = () => {
        setStatus("connected");
      };

      socket.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          setLastMessage(parsed);
          if (messageCallbackRef.current) {
            messageCallbackRef.current(parsed);
          }
        } catch {
          // ignore unparsable messages or ping frames
        }
      };

      socket.onerror = () => {
        setStatus("error");
      };

      socket.onclose = (event) => {
        setStatus("disconnected");
        wsRef.current = null;

        // If not closed normally and plate is still active, attempt reconnect in 3s
        if (!event.wasClean && plate) {
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, 3000);
        }
      };
    } catch {
      setStatus("error");
    }
  }, [plate]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const sendMessage = useCallback((data) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof data === "string" ? data : JSON.stringify(data));
      return true;
    }
    return false;
  }, []);

  return {
    status,
    isConnected: status === "connected",
    lastMessage,
    sendMessage,
    reconnect: connect,
  };
}

export default useWebSocket;
