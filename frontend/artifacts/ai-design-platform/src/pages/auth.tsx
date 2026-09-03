import { useEffect, useMemo, useState } from "react";
import { useLocation } from "wouter";
import { Loader2, LogIn, UserPlus } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { useCurrentUser, useLogin, useRegister } from "@/hooks/use-api";

type AuthMode = "login" | "register";

function isValidEmail(value: string): boolean {
  return value.includes("@");
}

function resolveNextPath(): string {
  if (typeof window === "undefined") {
    return "/";
  }
  const next = new URLSearchParams(window.location.search).get("next");
  if (!next || !next.startsWith("/")) {
    return "/";
  }
  return next;
}

export default function AuthPage() {
  const [, setLocation] = useLocation();
  const { data: currentUser, isLoading } = useCurrentUser();
  const register = useRegister();
  const login = useLogin();

  const [mode, setMode] = useState<AuthMode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const nextPath = useMemo(() => resolveNextPath(), []);
  const isSubmitting = register.isPending || login.isPending;

  useEffect(() => {
    if (!isLoading && currentUser) {
      setLocation(nextPath);
    }
  }, [currentUser, isLoading, nextPath, setLocation]);

  const submitLabel = mode === "register" ? "注册并进入" : "登录进入";
  const title = mode === "register" ? "创建你的账号" : "登录你的账号";
  const description =
    mode === "register"
      ? "先注册一个最基础账号，之后就可以进入首页和项目页面。"
      : "输入邮箱和密码后进入系统。";

  const validateForm = (): string => {
    // 教学注释：前端先做最基础校验，目的是让用户立刻知道哪里没填对，
    // 后端仍然会再校验一次，避免有人绕过页面直接发请求。
    if (mode === "register" && !name.trim()) {
      return "用户名不能为空";
    }
    if (!isValidEmail(email.trim())) {
      return "邮箱格式不对";
    }
    if (password.trim().length < 6) {
      return "密码至少 6 位";
    }
    return "";
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = validateForm();
    if (message) {
      setErrorMessage(message);
      return;
    }

    setErrorMessage("");

    try {
      // 设计注释：注册成功后直接当作已登录处理，省掉“注册完还要再登录一次”的重复动作。
      if (mode === "register") {
        await register.mutateAsync({
          name: name.trim(),
          email: email.trim().toLowerCase(),
          password: password.trim(),
        });
      } else {
        await login.mutateAsync({
          email: email.trim().toLowerCase(),
          password: password.trim(),
        });
      }
      setLocation(nextPath);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "提交失败，请稍后重试");
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background px-4 py-10">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(0,111,238,0.2),transparent_45%),linear-gradient(135deg,rgba(255,255,255,0.03),transparent_55%)]" />
      <div className="relative w-full max-w-5xl overflow-hidden rounded-[28px] border border-white/10 bg-black/30 shadow-[0_40px_120px_rgba(0,0,0,0.55)] backdrop-blur-xl">
        <div className="grid min-h-[680px] md:grid-cols-[1.15fr_0.85fr]">
          <section className="flex flex-col justify-between border-b border-white/10 px-6 py-8 md:border-b-0 md:border-r md:px-10 md:py-10">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs text-primary">
                Basic Auth
              </div>
              <h1 className="mt-6 max-w-md text-4xl font-semibold leading-tight text-foreground md:text-5xl">
                用真实账号进入你的 Agent IDE
              </h1>
              <p className="mt-4 max-w-lg text-sm leading-6 text-muted-foreground md:text-base">
                这次先做最基础的注册和登录，不加验证码，不加找回密码，只把最重要的进入流程先跑通。
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-sm font-medium text-foreground">1. 注册账号</p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">用用户名、邮箱、密码创建一个基础账号。</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-sm font-medium text-foreground">2. 登录进入</p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">登录成功后，首页和项目页才会开放。</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <p className="text-sm font-medium text-foreground">3. 安全退出</p>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">退出时会清掉本地登录令牌，回到认证页。</p>
              </div>
            </div>
          </section>

          <section className="flex items-center px-5 py-8 md:px-8">
            <div className="w-full rounded-[24px] border border-white/10 bg-card/85 p-6 shadow-2xl">
              <div className="mb-6 flex rounded-2xl border border-white/10 bg-background/70 p-1">
                <button
                  type="button"
                  className={`flex-1 rounded-xl px-4 py-2 text-sm transition ${mode === "login" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                  onClick={() => {
                    setMode("login");
                    setErrorMessage("");
                  }}
                >
                  登录
                </button>
                <button
                  type="button"
                  className={`flex-1 rounded-xl px-4 py-2 text-sm transition ${mode === "register" ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                  onClick={() => {
                    setMode("register");
                    setErrorMessage("");
                  }}
                >
                  注册
                </button>
              </div>

              <div>
                <h2 className="text-2xl font-semibold text-foreground">{title}</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{description}</p>
              </div>

              <form className="mt-8 space-y-4" onSubmit={(event) => void handleSubmit(event)}>
                {mode === "register" ? (
                  <div>
                    <label className="mb-2 block text-sm text-foreground">用户名</label>
                    <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：张三" />
                  </div>
                ) : null}

                <div>
                  <label className="mb-2 block text-sm text-foreground">邮箱</label>
                  <Input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="name@example.com"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm text-foreground">密码</label>
                  <Input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="至少 6 位"
                  />
                </div>

                {errorMessage ? (
                  <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-100">
                    {errorMessage}
                  </div>
                ) : null}

                <Button className="w-full" size="lg" disabled={isSubmitting} isLoading={isSubmitting} type="submit">
                  {mode === "register" ? <UserPlus className="mr-2 h-4 w-4" /> : <LogIn className="mr-2 h-4 w-4" />}
                  {submitLabel}
                </Button>
              </form>

              <p className="mt-5 text-xs leading-5 text-muted-foreground">
                {mode === "register" ? "已经有账号了？切换到登录即可。" : "还没有账号？切换到注册即可。"}
              </p>

              {isLoading ? (
                <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>正在检查当前登录状态...</span>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
