import type { ExecutionStats, StepRecord } from "@/hooks/use-api";

type UsageDisplayReason = "usage_pending" | "usage_unreported";
type TokenDirection = "input" | "output" | "total";

/**
 * 接口注释：
 * 统一把 token 数字转成更短的展示文案。
 * 规则固定为：
 * 1. 小于 1000 直接显示原值
 * 2. 千级显示为 k
 * 3. 百万级显示为 M
 * 4. 十亿及以上显示为 B
 * 5. 最多保留 1 位小数，像 1.0 这样的尾数会被去掉
 */
export function formatCompactTokenCount(value: number): string {
  if (!Number.isFinite(value)) {
    return "0";
  }

  const absoluteValue = Math.abs(value);
  if (absoluteValue < 1_000) {
    return String(value);
  }

  const units: Array<{ threshold: number; suffix: "k" | "M" | "B" }> = [
    { threshold: 1_000_000_000, suffix: "B" },
    { threshold: 1_000_000, suffix: "M" },
    { threshold: 1_000, suffix: "k" },
  ];

  for (const unit of units) {
    if (absoluteValue >= unit.threshold) {
      const shortened = value / unit.threshold;
      const rounded = Math.round(shortened * 10) / 10;
      // 设计注释：
      // 这里故意不继续向上换单位。
      // 比如 999.9M 不会因为四舍五入变成 1B，对用户来说这样更贴近真实区间。
      const formatted =
        Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1).replace(/\.0$/, "");
      return `${formatted}${unit.suffix}`;
    }
  }

  return String(value);
}

/**
 * 接口注释：
 * 这里专门判断“这份统计里是否已经有可展示的真实 token 数字”。
 * 只要任一方向已经累计出数字，就应该优先展示数字，而不是继续显示“未上报”。
 */
function hasConcreteStatisticsTokens(statistics: Pick<ExecutionStats, "tokens">): boolean {
  return statistics.tokens.input > 0 || statistics.tokens.output > 0 || statistics.tokens.total > 0;
}

function resolveUsageStatus(status: unknown): "pending" | "reported" | "unreported" {
  if (status === "pending" || status === "reported" || status === "unreported") {
    return status;
  }
  return "unreported";
}

/**
 * 接口注释：
 * 统一计算统计卡片里应该显示的耗时秒数。
 *
 * 设计注释：
 * 后端的 `totalDuration` 更像“已结算耗时”。
 * 在任务还没结束时，如果前端只显示这个值，数字只会在某个步骤结束后跳一下。
 * 所以这里补一层：只要任务还在跑，并且能拿到 `startedAt`，就按当前时间继续向前累加。
 */
export function resolveDisplayedDurationSeconds(
  statistics: Pick<ExecutionStats, "totalDuration" | "startedAt" | "completedAt" | "usageStatus">,
  nowMs: number = Date.now(),
): number {
  const settledDuration = Number.isFinite(statistics.totalDuration) ? Math.max(0, statistics.totalDuration) : 0;
  if (statistics.completedAt || statistics.usageStatus !== "pending") {
    return settledDuration;
  }

  const startedAtMs = Date.parse(String(statistics.startedAt || ""));
  if (!Number.isFinite(startedAtMs)) {
    return settledDuration;
  }

  const liveDuration = (nowMs - startedAtMs) / 1000;
  if (!Number.isFinite(liveDuration) || liveDuration <= 0) {
    return settledDuration;
  }
  return Math.max(settledDuration, liveDuration);
}

export function buildTokenDisplay(
  statistics: Pick<ExecutionStats, "tokens" | "usageStatus">,
  direction: TokenDirection = "total",
): { value: string; reason: UsageDisplayReason | null } {
  // 原因注释：
  // 流式统计接入后，后端可能已经把 token 累加上来了，但某些旧状态字段还没来得及对齐。
  // 这时如果继续只看 usageStatus，就会把真实数字误显示成“未上报”。
  if (hasConcreteStatisticsTokens(statistics)) {
    return {
      value: formatCompactTokenCount(statistics.tokens[direction]),
      reason: null,
    };
  }
  if (statistics.usageStatus === "pending") {
    return {
      value: "Processing",
      reason: "usage_pending",
    };
  }
  if (statistics.usageStatus === "unreported") {
    return {
      value: "Unreported",
      reason: "usage_unreported",
    };
  }
  return {
    value: formatCompactTokenCount(statistics.tokens[direction]),
    reason: null,
  };
}

export function buildExecutionStatsMeta(statistics: ExecutionStats) {
  const inputTokens = buildTokenDisplay(statistics, "input");
  const outputTokens = buildTokenDisplay(statistics, "output");

  return [
    { id: "model", value: statistics.model },
    {
      id: "inputTokens",
      value: inputTokens.value,
      reason: inputTokens.reason,
    },
    {
      id: "outputTokens",
      value: outputTokens.value,
      reason: outputTokens.reason,
    },
  ];
}

export function buildExecutionStatsSummary(statistics: ExecutionStats): {
  duration: string;
  steps: string;
  items: string;
  tokens: { value: string; reason: UsageDisplayReason | null };
} {
  const displayedDuration = resolveDisplayedDurationSeconds(statistics);
  return {
    duration: `${displayedDuration.toFixed(1)}s`,
    steps: String(statistics.stepsCount),
    items: String(statistics.itemsRead),
    tokens: buildTokenDisplay(statistics, "total"),
  };
}

export function buildAgentUsageBreakdown(
  statistics: Pick<ExecutionStats, "agentUsage">,
): Array<{
  agent: string;
  token: { value: string; reason: UsageDisplayReason | null };
  cost: number;
  model: string | null;
  usageStatus: "pending" | "reported" | "unreported";
}> {
  return (statistics.agentUsage ?? []).map((item) => ({
    agent: item.agent,
    token:
      item.totalTokens > 0
        ? {
            value: formatCompactTokenCount(item.totalTokens),
            reason: null,
          }
        : item.usageStatus === "pending"
          ? {
              value: "Processing",
              reason: "usage_pending" as const,
            }
          : item.usageStatus === "unreported"
            ? {
                value: "Unreported",
                reason: "usage_unreported" as const,
              }
            : {
                value: "0",
                reason: null,
              },
    cost: item.cost,
    model: item.model ?? null,
    usageStatus: item.usageStatus,
  }));
}

export function buildStepUsageMeta(step: StepRecord): {
  token: { value: string; reason: UsageDisplayReason | null };
  model: string | null;
  sourceAgent: string | null;
  usageStatus: "pending" | "reported" | "unreported";
  outputFiles: string[];
} {
  const metadata = step.metadata ?? {};
  // 教学注释：
  // 步骤卡片和总统计卡片要保持同一条规则：只要已经拿到 tokensUsed，就按“已上报”展示。
  // 这样就算 metadata.usageStatus 还是旧值，也不会把已经累计的数字盖掉。
  const usageStatus =
    step.tokensUsed > 0
      ? "reported"
      : resolveUsageStatus(metadata.usageStatus ?? "unreported");
  const token =
    usageStatus === "reported"
      ? {
          value: formatCompactTokenCount(step.tokensUsed),
          reason: null,
        }
      : usageStatus === "pending"
        ? {
            value: "Processing",
            reason: "usage_pending" as const,
          }
        : {
            value: "Unreported",
            reason: "usage_unreported" as const,
          };

  return {
    token,
    model: typeof metadata.model === "string" ? metadata.model : null,
    sourceAgent: typeof metadata.sourceAgent === "string" ? metadata.sourceAgent : null,
    usageStatus,
    outputFiles: Array.isArray(metadata.outputFiles)
      ? metadata.outputFiles.map((file) => String(file)).filter((file) => file.trim().length > 0)
      : [],
  };
}
