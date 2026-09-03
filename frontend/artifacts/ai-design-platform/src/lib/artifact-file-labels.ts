type TranslateFn = (key: string, options?: Record<string, unknown>) => string;

const ARTIFACT_FILE_LABEL_KEYS: Record<string, string> = {
  "survey.md": "artifact.fileLabel.survey",
  "draft_context_diagram.md": "artifact.fileLabel.draft_context_diagram",
  "draft_event_list.md": "artifact.fileLabel.draft_event_list",
  "user_introduction.md": "artifact.fileLabel.user_introduction",
  "feature_tree.md": "artifact.fileLabel.feature_tree",
  "business_scope.md": "artifact.fileLabel.business_scope",
  "BRD.md": "artifact.fileLabel.brd",
  "use_case.md": "artifact.fileLabel.use_case",
  "non_functional_requirements.md": "artifact.fileLabel.non_functional_requirements",
  "functional_requirements.md": "artifact.fileLabel.functional_requirements",
  "data_flow_diagram.md": "artifact.fileLabel.data_flow_diagram",
  "entity_relationship_diagram.md": "artifact.fileLabel.entity_relationship_diagram",
  "data_dictionary.md": "artifact.fileLabel.data_dictionary",
  "dialog_map.md": "artifact.fileLabel.dialog_map",
  "usage_scenario.md": "artifact.fileLabel.usage_scenario",
  "state_transition_diagram.md": "artifact.fileLabel.state_transition_diagram",
  "SRS.md": "artifact.fileLabel.srs",
  "analysis_task_output.txt": "artifact.fileLabel.analysis_task_output",
  "component_design.json": "artifact.fileLabel.component_design",
  "class_design_structured.json": "artifact.fileLabel.class_design_structured",
  "class_design_raw.md": "artifact.fileLabel.class_design_raw",
  "page_descriptions.json": "artifact.fileLabel.page_descriptions_json",
  "page_descriptions.md": "artifact.fileLabel.page_descriptions_md",
  "dar_model.json": "artifact.fileLabel.dar_model_json",
  "dar_model.md": "artifact.fileLabel.dar_model_md",
  "app/index.html": "artifact.fileLabel.app_index_html",
  "app/css/style.css": "artifact.fileLabel.app_css_style_css",
  "app/js/index.js": "artifact.fileLabel.app_js_index_js",
  "app/js/api.js": "artifact.fileLabel.app_js_api_js",
};

/**
 * 接口注释：
 * 通过真实文件名找到前端多语言 key。
 * 这样界面层可以根据当前语言切换标题，同时不影响后端保存的真实文件路径。
 */
export function artifactFileLabelKey(fileName: string): string | null {
  return ARTIFACT_FILE_LABEL_KEYS[fileName] ?? null;
}

/**
 * 设计注释：
 * 这里把“界面标题”和“文件正文”彻底分开：
 * - 标题永远走前端 i18n
 * - 正文永远保留 Agent 原文
 * 这样英文、日文等界面不会再硬塞中文标题，同时也不会篡改真实文档内容。
 */
export function localizeArtifactFileLabel(
  t: TranslateFn,
  fileName: string,
  fallbackLabel?: string | null,
): string {
  const labelKey = artifactFileLabelKey(fileName);
  if (!labelKey) {
    return fallbackLabel?.trim() || fileName;
  }

  return t(labelKey, {
    defaultValue: fallbackLabel?.trim() || fileName,
  });
}
