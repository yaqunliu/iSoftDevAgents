export type LineDiffRow =
  | {
      kind: "context" | "added" | "deleted";
      oldLineNumber: number | null;
      newLineNumber: number | null;
      content: string;
    }
  | {
      kind: "skipped";
      oldLineNumber: null;
      newLineNumber: null;
      content: string;
      skippedCount: number;
    };

function buildLcsTable(oldLines: string[], newLines: string[]): number[][] {
  const table = Array.from({ length: oldLines.length + 1 }, () =>
    Array.from({ length: newLines.length + 1 }, () => 0),
  );
  for (let oldIndex = oldLines.length - 1; oldIndex >= 0; oldIndex -= 1) {
    for (let newIndex = newLines.length - 1; newIndex >= 0; newIndex -= 1) {
      if (oldLines[oldIndex] === newLines[newIndex]) {
        table[oldIndex][newIndex] = table[oldIndex + 1][newIndex + 1] + 1;
      } else {
        table[oldIndex][newIndex] = Math.max(table[oldIndex + 1][newIndex], table[oldIndex][newIndex + 1]);
      }
    }
  }
  return table;
}

export function buildLineDiffRows(oldContent: string, newContent: string, contextWindow = 3): LineDiffRow[] {
  const oldLines = oldContent.split("\n");
  const newLines = newContent.split("\n");
  const table = buildLcsTable(oldLines, newLines);

  const rawRows: LineDiffRow[] = [];
  let oldIndex = 0;
  let newIndex = 0;
  let oldLineNumber = 1;
  let newLineNumber = 1;

  // 教学注释：
  // 这里用最稳定的“最长公共子序列”方式做行级 diff。
  // 速度不是最极致，但对当前这种文档和代码文件已经足够，而且结果可预期。
  while (oldIndex < oldLines.length && newIndex < newLines.length) {
    if (oldLines[oldIndex] === newLines[newIndex]) {
      rawRows.push({
        kind: "context",
        oldLineNumber,
        newLineNumber,
        content: oldLines[oldIndex],
      });
      oldIndex += 1;
      newIndex += 1;
      oldLineNumber += 1;
      newLineNumber += 1;
      continue;
    }
    if (table[oldIndex + 1][newIndex] >= table[oldIndex][newIndex + 1]) {
      rawRows.push({
        kind: "deleted",
        oldLineNumber,
        newLineNumber: null,
        content: oldLines[oldIndex],
      });
      oldIndex += 1;
      oldLineNumber += 1;
      continue;
    }
    rawRows.push({
      kind: "added",
      oldLineNumber: null,
      newLineNumber,
      content: newLines[newIndex],
    });
    newIndex += 1;
    newLineNumber += 1;
  }

  while (oldIndex < oldLines.length) {
    rawRows.push({
      kind: "deleted",
      oldLineNumber,
      newLineNumber: null,
      content: oldLines[oldIndex],
    });
    oldIndex += 1;
    oldLineNumber += 1;
  }

  while (newIndex < newLines.length) {
    rawRows.push({
      kind: "added",
      oldLineNumber: null,
      newLineNumber,
      content: newLines[newIndex],
    });
    newIndex += 1;
    newLineNumber += 1;
  }

  const changedIndexes = rawRows
    .map((row, index) => (row.kind === "context" ? -1 : index))
    .filter((index) => index >= 0);
  if (!changedIndexes.length) {
    return rawRows;
  }

  const keepIndexes = new Set<number>();
  for (const index of changedIndexes) {
    const start = Math.max(0, index - contextWindow);
    const end = Math.min(rawRows.length - 1, index + contextWindow);
    for (let cursor = start; cursor <= end; cursor += 1) {
      keepIndexes.add(cursor);
    }
  }

  const compactRows: LineDiffRow[] = [];
  let previousKeptIndex: number | null = null;
  for (let index = 0; index < rawRows.length; index += 1) {
    if (!keepIndexes.has(index)) {
      continue;
    }
    if (previousKeptIndex !== null && index - previousKeptIndex > 1) {
      const skippedCount = index - previousKeptIndex - 1;
      compactRows.push({
        kind: "skipped",
        oldLineNumber: null,
        newLineNumber: null,
        content: `... ${skippedCount} unchanged lines skipped ...`,
        skippedCount,
      });
    }
    compactRows.push(rawRows[index]);
    previousKeptIndex = index;
  }
  return compactRows;
}
