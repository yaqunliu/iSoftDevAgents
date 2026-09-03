export type AuthGateState =
  | { screen: "loading" }
  | { screen: "error" }
  | { screen: "ready" }
  | { screen: "redirect" };

export type AuthGateInput = {
  hasToken: boolean;
  hasCurrentUser: boolean;
  isLoading: boolean;
  isFetching: boolean;
  hasError: boolean;
};

// 接口注释：把鉴权页最外层的“该显示什么”做成纯函数，方便单测固定行为。
export function resolveAuthGateState(input: AuthGateInput): AuthGateState {
  if (!input.hasToken) {
    return { screen: "loading" };
  }

  if (input.hasCurrentUser) {
    return { screen: "ready" };
  }

  if (input.isLoading || input.isFetching) {
    return { screen: "loading" };
  }

  if (input.hasError) {
    return { screen: "error" };
  }

  return { screen: "redirect" };
}
