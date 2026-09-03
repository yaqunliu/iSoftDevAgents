"""需求工件输出语言识别的回归测试。

覆盖点：
- 用户描述用什么语言写，就应该识别成什么语言；
- 中文里夹杂英文技术名词时不能被误判成英文（真实用户最常见的写法）；
- agents.yaml / tasks.yaml 里的 {output_language_instruction} 占位符必须都能被填上，
  否则占位符会原样进入提示词。
"""

import importlib.util
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
REAGENT_ROOT = REPO_ROOT / "agent" / "Requirements Agent" / "reagent"
CONFIG_ROOT = REAGENT_ROOT / "src" / "reagent" / "config"


def _load_lang_detect():
    # reagent 的 util 包依赖 crewai，测试环境不一定装了，
    # 所以这里按文件路径单独加载 lang_detect，不走 `import util`。
    spec = importlib.util.spec_from_file_location(
        "reagent_lang_detect_under_test",
        REAGENT_ROOT / "util" / "lang_detect.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lang_detect = _load_lang_detect()


def _interpolate_only(text: str, inputs: dict) -> str:
    """近似 CrewAI 的 interpolate_only：只替换 inputs 里存在的键。"""
    for key, value in inputs.items():
        text = text.replace("{" + key + "}", str(value))
    return text


class DetectLanguageTests(unittest.TestCase):
    def test_detects_language_of_description(self) -> None:
        cases = [
            ("我们需要一个化学品追踪系统，支持化学师提交申请并扫描条形码。", "zh"),
            ("We need a chemical tracking system that lets chemists request chemicals.", "en"),
            ("Necesitamos un sistema que permita al usuario gestionar los pedidos.", "es"),
            ("Nous avons besoin d'un système que l'utilisateur doit utiliser pour les commandes.", "fr"),
            ("Wir brauchen ein System, das der Benutzer für die Bestellungen nutzen soll.", "de"),
            ("ユーザーが注文を管理できるシステムが必要です。", "ja"),
            ("사용자가 주문을 관리할 수 있는 시스템이 필요합니다.", "ko"),
            ("Нам нужна система, которая позволяет пользователю управлять заказами.", "ru"),
        ]
        for text, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(lang_detect.detect_language(text), expected)

    def test_chinese_with_english_technical_terms_stays_chinese(self) -> None:
        # 汉字承载的信息量接近一个英文单词，不能按字符数直接和字母数比较。
        text = "做一个交易社区平台，用户可以用 Python 编写 algorithmic trading strategies，通过 QuantRocket 做 backtest。"
        self.assertEqual(lang_detect.detect_language(text), "zh")

    def test_english_with_a_few_chinese_characters_stays_english(self) -> None:
        text = "A long English requirements document about the system. " * 20 + "中文"
        self.assertEqual(lang_detect.detect_language(text), "en")

    def test_blank_description_falls_back_to_default(self) -> None:
        for text in ("", "   ", "12345 !!!", None):
            with self.subTest(text=text):
                self.assertEqual(lang_detect.detect_language(text), lang_detect.DEFAULT_LANGUAGE)


class OutputLanguageInstructionTests(unittest.TestCase):
    def test_chinese_instruction_is_unchanged_behaviour(self) -> None:
        instruction = lang_detect.get_output_language_instruction("zh")
        self.assertIn("必须使用中文", instruction)

    def test_non_chinese_instruction_names_the_target_language(self) -> None:
        self.assertIn("English", lang_detect.get_output_language_instruction("en"))
        self.assertIn("Japanese", lang_detect.get_output_language_instruction("ja"))

    def test_unknown_language_code_falls_back_to_english(self) -> None:
        self.assertIn("English", lang_detect.get_output_language_instruction("xx"))

    def test_apply_injects_instruction_without_overwriting_caller(self) -> None:
        lang_detect.set_detected_language("en")
        self.addCleanup(lang_detect.set_detected_language, lang_detect.DEFAULT_LANGUAGE)

        original = {"project_name": "demo"}
        prepared = lang_detect.apply_output_language_instruction(original)

        self.assertNotIn("output_language_instruction", original)
        self.assertIn("English", prepared["output_language_instruction"])

        explicit = lang_detect.apply_output_language_instruction(
            {"output_language_instruction": "caller wins"}
        )
        self.assertEqual(explicit["output_language_instruction"], "caller wins")

    def test_detect_and_set_language_updates_shared_state(self) -> None:
        self.addCleanup(lang_detect.set_detected_language, lang_detect.DEFAULT_LANGUAGE)

        lang_detect.detect_and_set_language("Build a reporting dashboard for the finance team.")
        self.assertEqual(lang_detect.get_detected_language(), "en")

        lang_detect.detect_and_set_language("为财务团队做一个报表看板。")
        self.assertEqual(lang_detect.get_detected_language(), "zh")


class PromptPlaceholderTests(unittest.TestCase):
    """占位符没被填上就等于把 {output_language_instruction} 原样发给模型。"""

    def _assert_all_placeholders_resolved(self, path: Path, fields: tuple[str, ...]) -> None:
        config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        inputs = {"output_language_instruction": "INSTRUCTION"}
        unresolved = [
            (name, field)
            for name, entry in config.items()
            for field in fields
            if "{output_language_instruction}" in _interpolate_only(entry.get(field) or "", inputs)
        ]
        self.assertEqual(unresolved, [], f"unresolved placeholders in {path.name}")

    def test_every_task_declares_the_output_language_placeholder(self) -> None:
        for name in ("tasks.yaml", "tasks_eng.yaml"):
            path = CONFIG_ROOT / name
            config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            missing = [
                task
                for task, entry in config.items()
                if "{output_language_instruction}" not in (entry.get("expected_output") or "")
            ]
            self.assertEqual(missing, [], f"tasks without the placeholder in {name}")

    def test_task_placeholders_resolve(self) -> None:
        for name in ("tasks.yaml", "tasks_eng.yaml"):
            self._assert_all_placeholders_resolved(
                CONFIG_ROOT / name, ("description", "expected_output")
            )

    def test_agent_goal_carries_and_resolves_the_placeholder(self) -> None:
        agents = yaml.safe_load((CONFIG_ROOT / "agents.yaml").read_text(encoding="utf-8"))
        goal = agents["SoftwareManager"]["goal"]
        self.assertIn("{output_language_instruction}", goal)

        resolved = _interpolate_only(
            goal, {"output_language_instruction": lang_detect.get_output_language_instruction("en")}
        )
        self.assertNotIn("{output_language_instruction}", resolved)
        self.assertIn("English", resolved)
        # 中文硬编码必须已经被移除，否则海外客户仍然会拿到中文文档。
        self.assertNotIn("你的输出内容必须使用中文", resolved)


if __name__ == "__main__":
    unittest.main()
