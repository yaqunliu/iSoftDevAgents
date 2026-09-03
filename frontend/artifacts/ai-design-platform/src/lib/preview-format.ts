export type PreviewLanguage =
  | "markdown"
  | "ts"
  | "tsx"
  | "js"
  | "jsx"
  | "json"
  | "yaml"
  | "css"
  | "html"
  | "text";

export type CodeToken = {
  text: string;
  type: "plain" | "keyword" | "string" | "number" | "comment" | "property" | "tag";
};

const TS_KEYWORDS = new Set([
  "export",
  "const",
  "let",
  "var",
  "function",
  "return",
  "if",
  "else",
  "for",
  "while",
  "switch",
  "case",
  "break",
  "continue",
  "import",
  "from",
  "type",
  "interface",
  "class",
  "new",
  "await",
  "async",
  "true",
  "false",
  "null",
  "undefined",
]);

export function isMarkdownFileName(fileName: string): boolean {
  return /\.md|\.markdown$/i.test(fileName);
}

export function detectPreviewLanguage(fileName: string): PreviewLanguage {
  const normalized = fileName.toLowerCase();
  if (isMarkdownFileName(normalized)) return "markdown";
  if (normalized.endsWith(".tsx")) return "tsx";
  if (normalized.endsWith(".ts")) return "ts";
  if (normalized.endsWith(".jsx")) return "jsx";
  if (normalized.endsWith(".js")) return "js";
  if (normalized.endsWith(".json")) return "json";
  if (normalized.endsWith(".yaml") || normalized.endsWith(".yml")) return "yaml";
  if (normalized.endsWith(".css")) return "css";
  if (normalized.endsWith(".html") || normalized.endsWith(".htm")) return "html";
  return "text";
}

function tokenizeWithRegex(
  line: string,
  pattern: RegExp,
  classify: (match: string, groups: RegExpExecArray) => CodeToken["type"],
): CodeToken[] {
  const tokens: CodeToken[] = [];
  let lastIndex = 0;
  for (const groups of line.matchAll(pattern)) {
    const match = groups[0];
    const start = groups.index ?? 0;
    if (start > lastIndex) {
      tokens.push({ text: line.slice(lastIndex, start), type: "plain" });
    }
    tokens.push({ text: match, type: classify(match, groups as RegExpExecArray) });
    lastIndex = start + match.length;
  }
  if (lastIndex < line.length) {
    tokens.push({ text: line.slice(lastIndex), type: "plain" });
  }
  return tokens.length ? tokens : [{ text: line, type: "plain" }];
}

function highlightScriptLike(line: string): CodeToken[] {
  return tokenizeWithRegex(
    line,
    /\/\/.*$|"(?:\\.|[^"])*"|'(?:\\.|[^'])*'|`(?:\\.|[^`])*`|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b/g,
    (match) => {
      if (match.startsWith("//")) return "comment";
      if (match.startsWith("\"") || match.startsWith("'") || match.startsWith("`")) return "string";
      if (/^\d/.test(match)) return "number";
      if (TS_KEYWORDS.has(match)) return "keyword";
      return "plain";
    },
  );
}

function highlightJson(line: string): CodeToken[] {
  return tokenizeWithRegex(
    line,
    /"(?:\\.|[^"])*"(?=\s*:)|"(?:\\.|[^"])*"|\b\d+(?:\.\d+)?\b|\btrue\b|\bfalse\b|\bnull\b/g,
    (match, groups) => {
      const nextSlice = line.slice((groups.index ?? 0) + match.length);
      if (nextSlice.trimStart().startsWith(":")) return "property";
      if (match.startsWith("\"")) return "string";
      if (/^\d/.test(match)) return "number";
      return "keyword";
    },
  );
}

function highlightYaml(line: string): CodeToken[] {
  return tokenizeWithRegex(
    line,
    /#.*$|^\s*[^:#\n][^:\n]*?(?=\s*:)|"(?:\\.|[^"])*"|'(?:\\.|[^'])*'|\b\d+(?:\.\d+)?\b|\btrue\b|\bfalse\b|\bnull\b/g,
    (match) => {
      if (match.startsWith("#")) return "comment";
      if (match.startsWith("\"") || match.startsWith("'")) return "string";
      if (/^\d/.test(match)) return "number";
      if (/^(true|false|null)$/.test(match)) return "keyword";
      return "property";
    },
  );
}

function highlightCss(line: string): CodeToken[] {
  return tokenizeWithRegex(
    line,
    /\/\*.*\*\/|[.#]?[A-Za-z_-][\w-]*(?=\s*\{)|[A-Za-z-]+(?=\s*:)|"(?:\\.|[^"])*"|'(?:\\.|[^'])*'|\b\d+(?:\.\d+)?(?:px|rem|em|%)?\b/g,
    (match, groups) => {
      if (match.startsWith("/*")) return "comment";
      const nextSlice = line.slice((groups.index ?? 0) + match.length);
      if (nextSlice.trimStart().startsWith("{")) return "tag";
      if (nextSlice.trimStart().startsWith(":")) return "property";
      if (match.startsWith("\"") || match.startsWith("'")) return "string";
      if (/^\d/.test(match)) return "number";
      return "plain";
    },
  );
}

function highlightHtml(line: string): CodeToken[] {
  return tokenizeWithRegex(
    line,
    /<!--.*?-->|<\/?[A-Za-z][^>]*>|"(?:\\.|[^"])*"/g,
    (match) => {
      if (match.startsWith("<!--")) return "comment";
      if (match.startsWith("\"")) return "string";
      return "tag";
    },
  );
}

export function highlightCodeLine(line: string, language: PreviewLanguage): CodeToken[] {
  if (language === "ts" || language === "tsx" || language === "js" || language === "jsx") {
    return highlightScriptLike(line);
  }
  if (language === "json") {
    return highlightJson(line);
  }
  if (language === "yaml") {
    return highlightYaml(line);
  }
  if (language === "css") {
    return highlightCss(line);
  }
  if (language === "html") {
    return highlightHtml(line);
  }
  return [{ text: line, type: "plain" }];
}
