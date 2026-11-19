import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { ApiError, setUnauthenticatedHandler } from "./api";
import { applyTheme } from "./pages/Settings";
import { router } from "./routes";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
});

applyTheme();

setUnauthenticatedHandler(() => {
  queryClient.clear();
  if (window.location.pathname !== "/login") {
    void router.navigate(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
