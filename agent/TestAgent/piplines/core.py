from crewai import Task, Crew
from jinja2 import Template
from pathlib import Path


class PipelineStep:

    def __init__(self, *, agent, template_text: str, expected_output: str, output_file: str, usage_callback=None):
        self.agent = agent
        self.template_text = template_text
        self.expected_output = expected_output
        self.output_file = output_file
        self.usage_callback = usage_callback

    def _usage_payload_from_crew(self, crew):
        metrics = None
        try:
            if hasattr(crew, "calculate_usage_metrics"):
                metrics = crew.calculate_usage_metrics()
        except Exception:
            metrics = getattr(crew, "usage_metrics", None)

        if metrics is None:
            return None

        input_tokens = int(getattr(metrics, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(metrics, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(metrics, "total_tokens", 0) or 0)
        if total_tokens <= 0 and (input_tokens > 0 or output_tokens > 0):
            total_tokens = input_tokens + output_tokens
        if total_tokens <= 0 and input_tokens <= 0 and output_tokens <= 0:
            return None
        return {
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "totalTokens": total_tokens,
        }

    # 接口注释：
    # Test Agent 的三个步骤后面全都按“纯文本结果”继续处理，
    # 比如写 markdown、解析 json、保存 review 反馈。
    # 这里统一把 crewai 可能返回的流式包装对象拆成最终文本，
    # 这样后面的业务代码就不用到处判断返回值类型。
    def _normalize_output_text(self, output):
        if isinstance(output, str):
            return output

        # 教学注释：
        # 新版 crewai 在 stream=True 时会返回 CrewStreamingOutput。
        # 这个对象需要先被消费完，最终结果才会落到 .result 里。
        if hasattr(output, "is_completed") and hasattr(output, "__iter__") and not getattr(output, "is_completed"):
            for _ in output:
                pass

        result = getattr(output, "result", None)
        if result is not None:
            raw_text = getattr(result, "raw", None)
            if isinstance(raw_text, str) and raw_text:
                return raw_text

            json_value = getattr(result, "json", None)
            if isinstance(json_value, str) and json_value:
                return json_value

            content_text = getattr(result, "content", None)
            if isinstance(content_text, str) and content_text:
                return content_text

            if hasattr(result, "to_dict"):
                payload = result.to_dict()
                if payload:
                    return str(payload)

        if hasattr(output, "get_full_text"):
            full_text = output.get_full_text()
            if isinstance(full_text, str) and full_text:
                return full_text

        if result is not None:
            result_text = str(result)
            if result_text:
                return result_text

        raw_text = getattr(output, "raw", None)
        if isinstance(raw_text, str):
            return raw_text

        content_text = getattr(output, "content", None)
        if isinstance(content_text, str):
            return content_text

        return str(output)

    def run(self, **kwargs):

        template = Template(self.template_text)
        description = template.render(**kwargs)

        task = Task(
            description=description,
            expected_output=self.expected_output,
            agent=self.agent,
            output_file=self.output_file
        )

        crew = Crew(
            agents=[self.agent],
            tasks=[task],
            verbose=False,
            stream=True

        )

        # 启动任务执行
        streaming_output = crew.kickoff()
        if self.usage_callback is not None:
            usage_payload = self._usage_payload_from_crew(crew)
            if usage_payload is not None:
                self.usage_callback(usage_payload)
        normalized_output = self._normalize_output_text(streaming_output)

        # 原因注释：
        # 在 stream=True 的场景下，底层库并不稳定保证一定帮我们把 output_file 写出来。
        # 但 Test Agent 后续的收尾检查明确依赖这些文件是否存在，
        # 所以这里由我们自己把最终文本落盘，避免“内容已经生成了，文件却缺席”的假失败。
        output_path = str(self.output_file or "").strip()
        if output_path:
            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(normalized_output, encoding="utf-8")

        return normalized_output
