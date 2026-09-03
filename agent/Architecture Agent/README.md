## Architecture Agent 代码介绍

### 代码文件结构

Architecture Agent/
- data/
  - input/ 输入数据目录
    - 代码审查管理平台.md 示例需求文档
  - output/ 输出工件位置
    - {timestamp}_{project_name}/ 按时间戳和项目名生成的输出目录
      - component_design.json 组件设计结构化数据
      - class_design_structured.json 类设计结构化数据
      - class_design_raw.md 类设计原始文档
      - 其他中间结果
- src/arch_agent/ 核心代码目录
  - config/ 配置文件目录 (agents.yaml, tasks.yaml)
  - crew.py 定义 CrewAI 的 Agent、Task 以及带有缓存的 LLM 配置
  - flow.py 定义基于 CrewAI Flow 的架构设计工作流 (ArchiFlow)
  - main.py 程序入口，支持运行、训练、回放和测试命令

### 使用方法

```
usage: main.py [-h] [requirements_path] [project_name]

Run the ArchAgent crew.

positional arguments:
  requirements_path  Path to the requirements document (e.g., SRS file).
  project_name       Name of the project. If not provided, it will be derived from the  
                     requirements file name.

options:
  -h, --help         show this help message and exit

示例:
  python src/arch_agent/main.py "data/input/代码审查管理平台.md"
  python src/arch_agent/main.py "data/input/代码审查管理平台.md" "CodeReviewPlatform"
```
