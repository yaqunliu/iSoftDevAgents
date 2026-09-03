# 代码文件结构

reagent/
- data/ 存储项目描述
- output/ 输出工件位置
  - artifact_planning.md 模板章节的工件规划
  - BRD_modify.md BRD人工返回修改后模型生成的需求工件范围以及修改意见
  - BRD.md 业务需求文档的内容
  - business_requirements_chapter.md 业务需求文档按章生成的临时存储文件
  - business_scope.md 业务范围文档
  - BusinessRequirementDocument.pkl BRD的数据结构
  - chapter_dependence.md 模板的章节间依赖
  - data_dictionary.md 数据字典
  - data_flow_diagram.md 数据流图
  - dialog_map.md 对话图
  - doc_content.md 提取SRS整体内容的文件
  - draft_context_diagram.md 上下文图
  - draft_event_list.md 外部事件列表
  - entity_relationship_diagram.md 实体关系图
  - feature_tree.md 系统特征树
  - functional_requirements.md 功能性需求
  - non_functional_requirements.md 非功能需求/质量保证
  - software_requirements_specification_chapter.md SRS按章生成的临时产物
  - srs_planning.md SRS按章节写作规划的临时存储文件
  - SRS.md SRS的内容
  - SRS.pkl SRS的数据结构
  - state_transition_diagram.md 状态转移图
  - survey.md 调研
  - usage_scenario.md 使用场景
  - use_case.md 用例的内容
  - UseCase.pkl 用例的数据结构
  - user_introduction.md 用户类与特征介绍
- src/reagent/ BRD 和 SRS 照章生成
  - config/ 配置文件
  - template/ 需求模板的对应信息，按照哈希存储
  - tools/
  - BusinessRequirements.py 业务需求过程 生成业务需求文档 用户介绍 上下文图
  - main.py
  - MetaAnalysis.py 模板逆向分析
  - NonStandardProcess 导出工件生成
  - RequirementElicitation.py 需求获取过程 
  - RequirementAnalysis.py 需求分析过程 
  - RequirementSpecification.py 需求规约过程 
  - StandardProcess.py 默认流程工件生成
- util/
  - doc_template/ 文档模板类的相关代码
  - Artifact.py 工件的结构化提示词
  - DAG.py 有向无环图相关代码
  - SoftwareManager.py 软件经理的代码
  - user_case.py 用户用例类的相关代码
  - util.py 其他接口，主要是增删改查数据结构以及各个工件的代码
  - validate_format.py 校验数据结构的函数
- crewAI_README.md crewAI readme
- reagent_readme.md
- requirements.txt
- start.sh 启动脚本

# 启动脚本示例
python src/reagent/main.py \
  --project_name "自动化软件源代码审查平台" \
  --description_file "data/project_description.txt" \
  --srs_example_path "util/doc_template/document_example.md" \

参数：project_name-项目名、description_file-初始需求文档、srs_example_path-srs文档路径

# 人工干预
在业务范围文档、用例之间会有可以人工干预的部分
为了让人工干预更加清楚建议在干预的时候使用一些需求的术语。
例如：
“我希望在与外部实体xxx的交互中增加xxx”
“我希望用例中可以增加xxx”
