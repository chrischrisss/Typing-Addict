import { useEffect, useLayoutEffect, useRef } from "react";
import { io } from "socket.io-client";

export function useLobbySocket(lobbyCode, handlers = {}) {
  const handlersRef = useRef(handlers);

  useLayoutEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    if (!lobbyCode) {
      return undefined;
    }

    const socket = io({
      path: "/socket.io",
      withCredentials: true,
      query: { lobby: lobbyCode },
    });

    socket.on("lobby:updated", (data) => {
      handlersRef.current.onLobbyUpdated?.(data);
    });
    socket.on("game:state", (data) => {
      handlersRef.current.onGameState?.(data);
    });
    socket.on("lobby:closed", (data) => {
      handlersRef.current.onClosed?.(data);
    });
    socket.on("connect_error", () => {
      handlersRef.current.onError?.();
    });

    return () => {
      socket.disconnect();
    };
  }, [lobbyCode]);
}
