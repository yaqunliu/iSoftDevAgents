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
import LandingPage from "@/pages/landing";
import TermsPage from "@/pages/terms";
import PrivacyPage from "@/pages/privacy";
import ContactPage from "@/pages/contact";
import { getStoredAuthToken, useCurrentUser } from "@/hooks/use-api";
import { APP_HOME_PATH } from "@/lib/app-routes";
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

      {/* 官网页面是公开路由，不能包 ProtectedRoute——
          市场访客没有 token，包上之后会被直接踢到 /auth，官网也就打不开了。
          条款页和隐私页同理，而且这两页还有一层额外理由：
          应用商店和合规审查会直接访问这两个地址，必须匿名可达。

          原因注释：官网占用根路径 "/"，产品首页因此搬到了 APP_HOME_PATH。
          这不只是路由表里换个位置——登录回跳、项目页返回、404 返回
          原本都指向 "/"，那五处已经一并改到了 APP_HOME_PATH。
          如果将来要把官网移走，务必连着那五处一起改，
          否则会出现"点返回却跳到营销页"这类不报错的静默故障。 */}
      <Route path="/" component={LandingPage} />
      <Route path="/terms" component={TermsPage} />
      <Route path="/privacy" component={PrivacyPage} />
      <Route path="/contact" component={ContactPage} />

      {/* /landing 是官网上线前用过的临时地址。保留一个重定向，
          因为这个链接可能已经被人存进书签或发给过客户，
          直接删掉会让那些链接落到 404。成本一行，收益是不丢访客。 */}
      <Route path="/landing" component={LegacyLandingRedirect} />

      <Route path={APP_HOME_PATH}>
        <ProtectedRoute component={Home} />
      </Route>
      <Route path="/project/:id">
        <ProtectedRoute component={ProjectPage} />
      </Route>
      <Route component={NotFound} />
    </Switch>
  );
}

/**
 * 旧官网地址 /landing 的重定向。
 *
 * 教学注释：用 replace 而不是普通跳转——访客的历史记录里不该留下 /landing 这一格，
 * 否则他点浏览器后退会回到 /landing，然后又被重定向到 /，
 * 形成一个后退键失灵的陷阱。
 */
function LegacyLandingRedirect() {
  const [, setLocation] = useLocation();

  useEffect(() => {
    setLocation("/", { replace: true });
  }, [setLocation]);

  return null;
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
    // 原因注释：兜底值是 APP_HOME_PATH 而不是 "/"——"/" 现在是官网营销页，
    // 用它兜底会让登录成功的用户落在市场页上，看起来像登录没生效。
    if (!hasToken) {
      setLocation(`/auth?next=${encodeURIComponent(location || APP_HOME_PATH)}`);
      return;
    }
    if (gateState.screen === "redirect") {
      setLocation(`/auth?next=${encodeURIComponent(location || APP_HOME_PATH)}`);
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
