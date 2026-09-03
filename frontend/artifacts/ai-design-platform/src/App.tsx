import { type ComponentType, useEffect } from "react";
import { Switch, Route, Router as WouterRouter, useLocation } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui";

// Pages
import AuthPage from "@/pages/auth";
import Home from "@/pages/home";
import ProjectPage from "@/pages/project";
import NotFound from "@/pages/not-found";
import { getStoredAuthToken, useCurrentUser } from "@/hooks/use-api";
import { resolveAuthGateState } from "@/lib/auth-gate-state";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 1000 * 60 * 5, // 5 mins
    },
  },
});

function Router() {
  return (
    <Switch>
      <Route path="/auth" component={AuthPage} />
      <Route path="/">
        <ProtectedRoute component={Home} />
      </Route>
      <Route path="/project/:id">
        <ProtectedRoute component={ProjectPage} />
      </Route>
      <Route component={NotFound} />
    </Switch>
  );
}

function FullScreenLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
      <div className="flex items-center gap-3 text-sm">
        <Loader2 className="h-4 w-4 animate-spin text-primary" />
        <span>Loading...</span>
      </div>
    </div>
  );
}

function FullScreenError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6 text-foreground">
      <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-card/80 p-8 shadow-2xl">
        <h1 className="text-lg font-semibold">Backend unavailable</h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">{message}</p>
        <div className="mt-6 flex gap-3">
          <Button onClick={onRetry}>Retry</Button>
          <Button variant="outline" onClick={() => window.location.reload()}>
            Refresh Page
          </Button>
        </div>
      </div>
    </div>
  );
}

function ProtectedRoute({ component: Component }: { component: ComponentType }) {
  const hasToken = Boolean(getStoredAuthToken());
  const { data: currentUser, isLoading, isFetching, isError, error, refetch } = useCurrentUser();
  const [location, setLocation] = useLocation();
  const gateState = resolveAuthGateState({
    hasToken,
    hasCurrentUser: Boolean(currentUser),
    isLoading,
    isFetching,
    hasError: isError,
  });

  useEffect(() => {
    // 这里把原目标地址带到认证页，登录成功后可以回跳。
    if (!hasToken) {
      setLocation(`/auth?next=${encodeURIComponent(location || "/")}`);
      return;
    }
    if (gateState.screen === "redirect") {
      setLocation(`/auth?next=${encodeURIComponent(location || "/")}`);
    }
  }, [gateState.screen, hasToken, location, setLocation]);

  if (gateState.screen === "loading") {
    return <FullScreenLoading />;
  }

  if (gateState.screen === "error") {
    const message =
      error instanceof Error
        ? error.message
        : "The backend API is not responding. Check the service on port 9010 and retry.";
    return <FullScreenError message={message} onRetry={() => void refetch()} />;
  }

  if (gateState.screen === "redirect") {
    return null;
  }

  return <Component />;
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
          <Router />
        </WouterRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default App;
