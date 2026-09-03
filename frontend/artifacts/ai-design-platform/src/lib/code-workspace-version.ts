export function resolveCodeWorkspaceVersion(
  requestedVersion: number | null | undefined,
  currentVersion: number | null | undefined,
  pendingVersion: number | null | undefined,
): number | undefined {
  if (typeof requestedVersion === "number" && typeof currentVersion === "number" && requestedVersion !== currentVersion) {
    return requestedVersion;
  }
  if (typeof requestedVersion === "number" && typeof currentVersion !== "number") {
    return requestedVersion;
  }

  // 设计注释：
  // 聊天里的“步骤产物”和右侧代码工作区，必须尽量看同一轮真实数据。
  // 只要当前轮已经有待确认预览版本，就优先切到这个版本，
  // 这样左侧文件列表才能立刻出现刚刚生成出来的文档，不会再落后于聊天进度。
  //
  // 教学注释：
  // 这里返回的是“工作区应该读取哪个版本的数据”，不是“项目正式版本已经提交”。
  // 前端会继续通过 `isPendingPreview` 打上“预览 vX”标记，避免用户误会。
  if (
    typeof pendingVersion === "number" &&
    (
      typeof currentVersion !== "number" ||
      pendingVersion > currentVersion
    )
  ) {
    return pendingVersion;
  }

  return undefined;
}
