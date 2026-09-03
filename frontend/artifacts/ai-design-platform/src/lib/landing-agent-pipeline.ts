/**
 * 接口注释：
 * 官网"五个 Agent 接力"区块的数据模型和状态推导。
 *
 * 设计注释：
 * 这里刻意不把文案写进来，只留 i18n key。原因是官网要走 react-i18next，
 * 文案归 lib/i18n-landing-locales.ts 管，这份文件只描述"结构"——
 * 有几个阶段、每个阶段产出什么、状态怎么算。结构和文案分开，
 * 以后加语言不需要碰这里，改流水线顺序也不需要碰文案。
 */

/** Agent 阶段在演示动画里的运行状态。 */
export type StageState = "pending" | "running" | "done";

export type PipelineStage = {
  /** 稳定标识，同时用作 React key 和 i18n key 的后缀。 */
  id: string;
  /** 阶段序号，展示成 01 / 02 这种编号。 */
  index: number;
  /**
   * 该阶段产出的关键产物的 i18n key 后缀。
   * 教学注释：产物列表是这个区块最有说服力的部分——评审者关心的是"给我什么文件"，
   * 而不是"你用了几个 Agent"，所以每个阶段都必须列清楚产物。
   */
  artifactKeys: string[];
};

/**
 * 设计注释：
 * 五个阶段的顺序和产物严格对齐产品实际行为：
 * 需求分析产出 SRS 和 PRD，架构设计产出系统方案和架构图，UI 产出高保真原型，
 * 编码产出完整代码工作区，测试补齐测试用例。
 * 这里不做任何夸大——官网上每一个产物名都应该能在产品里找到对应文件。
 */
export const PIPELINE_STAGES: PipelineStage[] = [
  {
    id: "requirements",
    index: 1,
    artifactKeys: ["srs", "prd"],
  },
  {
    id: "architecture",
    index: 2,
    artifactKeys: ["systemDesign", "diagram"],
  },
  {
    id: "ui",
    index: 3,
    artifactKeys: ["prototype"],
  },
  {
    id: "coding",
    index: 4,
    artifactKeys: ["workspace"],
  },
  {
    id: "testing",
    index: 5,
    artifactKeys: ["testCases"],
  },
];

export const PIPELINE_STAGE_COUNT = PIPELINE_STAGES.length;

/**
 * 根据"当前正在跑第几个阶段"推导某个阶段的状态。
 *
 * 原因注释：
 * 官网的流水线是一个循环播放的演示动画，activeIndex 由组件用定时器递增。
 * 把状态推导抽成纯函数，是为了让这段逻辑可测、并且组件里不再出现
 * `i < active ? 'done' : i === active ? 'running' : 'pending'` 这种难读的三元嵌套。
 */
export function resolveStageState(stageIndex: number, activeIndex: number): StageState {
  if (stageIndex < activeIndex) {
    return "done";
  }
  if (stageIndex === activeIndex) {
    return "running";
  }
  return "pending";
}

/**
 * 演示动画推进到下一个阶段，跑完最后一个阶段后从头开始。
 *
 * 教学注释：
 * 取模写法能自动处理回绕，不需要写 if (next > count) next = 1。
 * 阶段序号从 1 开始，所以先减一再取模、最后加回来。
 */
export function nextActiveIndex(activeIndex: number, stageCount: number = PIPELINE_STAGE_COUNT): number {
  if (stageCount <= 0) {
    return 1;
  }
  return ((activeIndex % stageCount) + stageCount) % stageCount + 1;
}

/**
 * 已完成阶段数占总数的百分比，用于流水线顶部那根进度条。
 */
export function pipelineProgressPercent(
  activeIndex: number,
  stageCount: number = PIPELINE_STAGE_COUNT,
): number {
  if (stageCount <= 0) {
    return 0;
  }
  const clamped = Math.min(Math.max(activeIndex, 0), stageCount);
  return Math.round((clamped / stageCount) * 100);
}
