from util.doc_template.SoftwareRequirementSpecification.SRS import SoftwareRequirementSpecification
from util.doc_template.chapter import CHAPTER


def Create_SRS_438C_Template(authors: str) -> SoftwareRequirementSpecification:
    title = "软件需求规格说明"
    introduction = '本文档描述了项目的软件需求规格说明。'
    SRS = SoftwareRequirementSpecification(title, introduction, authors)

    chapters_1 = CHAPTER(
        title="范围",
        introduction="本章应描述本文档所适用软件的完整标识及其用途概述。"
    )
    Create_Scope(SRS, chapters_1)

    chapters_2 = CHAPTER(
        title="引用文档",
        introduction="""本章应列出引用文档的编号、标题、编写单位、修订版及日期，还应标识不能通过正常采购活动得到的文档的来源。"""
    )
    SRS.add_subchapter(chapters_2)

    chapters_3 = CHAPTER(
        title="需求",
        introduction="本章应详细说明软件的各项需求。"
    )
    Create_Requirements(SRS, chapters_3)

    chapters_4 = CHAPTER(
        title="合格性规定",
        introduction="""本条应描述所定义的合格性方法，并为第3章中的每个需求指定为确保需求得到满足所要使用的方法。可用表格形式表述该信息，或为第3章中的每个需求注明所使用的方法。
合格性方法：
a) A-演示：对CSCI（或部分CSCI）进行直接可以观察的功能操作，不需要使用复杂或专用的测试设备；
b) B-测试；
c) C-分析；
d) D-检查：对CSCI的编码、文档等进行直观检查等；
e) E-特殊方法（如：专用工具、技术、过程、设施、验收限制）。
合格性级别：
a) a-配置项：在CSCI中发现的质量问题；
b) b-系统集成：在系统集成时发现的问题；
c) c-系统：在系统中发现的质量问题；
d) d-系统安装：在系统安装时发现的质量问题。"""
    )
    SRS.add_subchapter(chapters_4)

    chapters_5 = CHAPTER(
        title="需求可追踪性",
        introduction="""本章应描述需求的正向追踪性和逆向追踪性，建立上级文档指标与软件需求之间的对应关系。"""
    )
    SRS.add_subchapter(chapters_5)

    chapters_6 = CHAPTER(
        title="注释",
        introduction="""本章应包括有助于了解文档的所有信息，例如：背景、术语、缩略语或公式。"""
    )
    SRS.add_subchapter(chapters_6)

    return SRS


def Create_Scope(SRS: SoftwareRequirementSpecification, chapter: CHAPTER):
    scope_1_1 = CHAPTER(
        title="标识",
        introduction="""本条应描述本文档所适用软件的完整标识，适用时，包括其标识号、名称、缩略名、版本号和发布号。
a）文档标识号；
b）标题；
c）软件名称；
d）软件缩写；
e）软件版本号。"""
    )
    scope_1_2 = CHAPTER(
        title="系统概述",
        introduction="""本条应概述本文档所适用软件的用途。它还应描述软件的一般特性，概述系统开发、运行和维护的历史；标识项目的需方、用户、开发方和保障机构等；标识当前和计划的运行现场；列出其他有关文档。"""
    )
    scope_1_3 = CHAPTER(
        title="文档概述",
        introduction="""本条应概述本文档的用途和内容，并描述与它的使用有关的保密性方面的要求。"""
    )
    SRS.add_subchapter(chapter)
    chapter.add_subchapter(scope_1_1)
    chapter.add_subchapter(scope_1_2)
    chapter.add_subchapter(scope_1_3)


def Create_Requirements(SRS: SoftwareRequirementSpecification, chapter: CHAPTER):
    req_3_1 = CHAPTER(
        title="要求的状态和方式",
        introduction="""如果要求软件在多种状态或方式下运行，并且不同的状态或方式具有不同的需求，则应标识和定义每一状态和方式。状态和方式的例子包括：空闲、就绪、活动、事后分析、训练、降级、紧急情况、后备、战时和平时等。可以仅用状态描述软件也可以仅用方式、用方式中的状态、状态中的方式、或其他有效的方式描述软件。如果不需要多种状态和方式，应如实陈述，而不需要进行人为的区分；如果需要多种状态和/或方式，应使本规格说明中的每个需求或每组需求与这些状态和方式相对应。"""
    )
    req_3_2 = CHAPTER(
        title="软件能力需求",  # 可变章节
        introduction="""为详细说明与软件各个能力相关的需求，本条可分为若干子条。"软件能力需求"中的"能力"为一组相关需求，可用"功能"、"主题"、"对象"、或其他适合表示需求的词替代。需求应详细说明所需的软件行为，包括适用的参数，如响应时间、吞吐时间、其他时限约束、时序、精度、容量、优先级别、连续运行需求和在基本运行条件下允许的偏差；适当时，需求还应包括在异常条件、非许可条件或超限条件下所需的行为，错误处理需求和任何为保证在紧急时刻运行的连续性而引入到软件中的规定。"""
    )
    req_3_3 = CHAPTER(
        title="软件外部接口需求",  # 可变章节
        introduction="""本条可分为若干个小条来规定关于软件的外部接口的需求（若有）。本条可引用一个或多个接口需求规格说明（IRS）或包含这些需求的其他文档。应标识所需要的软件外部接口（即，与涉及共享、提供或交换数据的其他实体的关系）。每一个接口的标识应包括项目唯一的标识符，（若适用）应通过名称、编号、版本、引用文档来指明接口实体（系统、配置项、用户等）。"""
    )
    Create_External_Interface_Requirements(chapter, req_3_3)

    req_3_4 = CHAPTER(
        title="软件内部接口需求",
        introduction="""本条应描述施加于软件内部接口的需求（若有）。如果所有内部接口都留待设计时再描述，那么应在此如实陈述。"""
    )
    req_3_5 = CHAPTER(
        title="软件内部数据需求",
        introduction="""本条应描述施加于软件内部数据的需求（若有），包括对软件中数据库和数据文件的需求（若有）。如果关于内部数据的所有决策都留待设计时再考虑，那么应在此如实陈述。"""
    )
    req_3_6 = CHAPTER(
        title="适应性需求",
        introduction="""本条应描述关于软件将提供的与安装有关的数据（如场地的经纬度或场地所在地的赋税代码）的需求（若有），应指定对要求软件使用的运行参数（如指明与运行有关的目标常数或数据记录的参数）的需求，这些运行参数可以根据运行需要而改变。"""
    )
    req_3_7 = CHAPTER(
        title="安全性需求",
        introduction="""本条应描述关于防止或尽可能降低对人员、财产和物理环境产生意外危险的软件需求（若有）。例子包括：软件必须提供的安全措施，以便防止意外动作（例如意外地发出一个"自动导航关闭"命令）和无动作（例如发出"自动导航关闭"命令失败）。本条还应包括关于系统的核部件的软件需求（若有），若适用应包括预防意外爆炸以及与核安全规则保持一致等方面的需求。"""
    )
    req_3_8 = CHAPTER(
        title="保密性需求",
        introduction="""本条应描述与维护保密性有关的软件需求（若有）。（若适用）这些需求应包括：软件必须在其中运行的保密性环境、所提供的保密性的类型和级别、软件必须经受的保密性风险、减少此类风险所需的安全措施、必须遵循的保密性政策、软件必须具备的保密性责任、保密性认证/认可必须满足的准则等。"""
    )
    req_3_9 = CHAPTER(
        title="软件环境需求",
        introduction="""本条应描述软件的运行环境需求（若有），如在其上运行软件的计算机硬件和操作系统。"""
    )
    req_3_10 = CHAPTER(
        title="计算机资源需求",
        introduction="本条应描述软件对计算机资源的各项需求。"
    )
    Create_Computer_Resource_Requirements(chapter, req_3_10)

    req_3_11 = CHAPTER(
        title="软件质量因素",
        introduction="""本条应描述合同（或软件研制任务书）规定的或由较高一级规格说明派生出的软件质量因素方面的软件需求（若有）。例子包括有关软件功能性、可靠性、易用性、效率、维护性、可移植性和其他属性的定量要求。"""
    )
    req_3_12 = CHAPTER(
        title="设计和实现约束",
        introduction="""本条应描述约束软件的设计和实现的那些需求（若有）。这些需求可引用相应的商用或军用标准和规范来指定。例子包括关于以下各方面的需求：
a）使用一个特定的软件体系结构，或针对体系结构的要求，例如所要求的数据库或其他软件单元；使用标准的或现有的部件；或使用由政府/需方提供的资源（设备、信息或软件）；
b）使用特定的设计或实现标准；使用特定的数据标准；使用特定的编程语言；
c）为支持在技术、威胁或使命方面预期的增长或变化，必须提供的灵活性和可扩展性。"""
    )
    req_3_13 = CHAPTER(
        title="人员需求",
        introduction="""本条应描述与使用或支持本软件的人员有关的软件需求（若有），包括人员的数量、技术水平、责任期限、培训要求或其他信息。例子包括要求允许多少用户同时工作，以及嵌入的帮助和培训等方面的需求；还应包括施加于软件的人素工程需求（若有）。（适用时）这些需求应包括对人的能力和局限性的考虑，在正常和极端条件下可预见的人为错误，以及人为错误影响特别严重的那些特定场合。"""
    )
    req_3_14 = CHAPTER(
        title="培训需求",
        introduction="""本条应描述与培训有关的软件需求（若有）。"""
    )
    req_3_15 = CHAPTER(
        title="软件保障需求",
        introduction="""本条应描述与软件保障考虑有关的软件需求（若有）。这些考虑可以包括：对系统维护、软件保障、系统运输方式、补给系统的要求、对现有设施的影响和对现有设备的影响。"""
    )
    req_3_16 = CHAPTER(
        title="其他需求",
        introduction="""本条应描述上述各条未能覆盖的其他软件需求（若有）。"""
    )
    req_3_17 = CHAPTER(
        title="验收、交付和包装需求",
        introduction="""本条应描述为了交付而对软件进行包装、加标记和处理的需求（若有）。（若适用）可引用适当的标准。"""
    )
    req_3_18 = CHAPTER(
        title="需求的优先顺序和关键程度",
        introduction="""本条（若适用）应描述本文档中诸需求的优先顺序、关键程度、或所赋予的指明其相对重要性的权值。例子包括，指明那些被认为对安全性或保密性至关重要的需求，以便将这些需求作特殊处理。如果全部需求同等重要，本条应如实陈述。"""
    )

    SRS.add_subchapter(chapter)
    chapter.add_subchapter(req_3_1)
    chapter.add_subchapter(req_3_2)
    chapter.add_subchapter(req_3_3)
    chapter.add_subchapter(req_3_4)
    chapter.add_subchapter(req_3_5)
    chapter.add_subchapter(req_3_6)
    chapter.add_subchapter(req_3_7)
    chapter.add_subchapter(req_3_8)
    chapter.add_subchapter(req_3_9)
    chapter.add_subchapter(req_3_10)
    chapter.add_subchapter(req_3_11)
    chapter.add_subchapter(req_3_12)
    chapter.add_subchapter(req_3_13)
    chapter.add_subchapter(req_3_14)
    chapter.add_subchapter(req_3_15)
    chapter.add_subchapter(req_3_16)
    chapter.add_subchapter(req_3_17)
    chapter.add_subchapter(req_3_18)


def Create_External_Interface_Requirements(parent_chapter: CHAPTER, chapter: CHAPTER):
    eir_3_3_1 = CHAPTER(
        title="接口标识和接口图",
        introduction="""本条应标识所需要的软件外部接口（即，与涉及共享、提供或交换数据的其他实体的关系）。每一个接口的标识应包括项目唯一的标识符，（若适用）应通过名称、编号、版本、引用文档来指明接口实体（系统、配置项、用户等）。该标识应声明哪些实体具有固定的接口特性（要给出这些接口实体的接口需求）；说明哪些实体正在开发或修改之中（这些实体已有各自的接口需求）。应该通过一张或多张接口图来描述这些接口。"""
    )
    eir_3_3_2 = CHAPTER(
        title="接口的项目唯一的标识符",  # 可变章节
        introduction="""本条应通过项目唯一的标识符来标识软件外部接口，应简要地标识接口实体。视需要可分小条描述为实现该接口提出的该软件的需求。（若适用）需求应包括如下内容：
a）软件必须分配给该接口的优先级。
b）对要实现的接口类型的要求（例如实时数据传送、数据的储存和检索等）。
c）软件必须提供、储存、发送、存取、接收的各个数据元素所要求的特征，例如：
   1）名称/标识符；2）数据类型；3）大小和格式；4）计量单位；5）可能值的范围或枚举；6）准确性和精度；7）优先级别、定时、频率、容量、序列以及其他约束条件；8）保密性约束；9）来源和接收者。
d）软件必须提供、存储、发送、访问、接收的数据元素组合体（记录、消息、文件、数组、显示、报表等）所要求的特征。
e）软件必须使用的接口的通信方法所要求的特征。
f）软件必须使用的接口的协议所要求的特征。
g）其他所需要的特征，例如接口实体的物理兼容性等。"""
    )
    chapter.add_subchapter(eir_3_3_1)
    chapter.add_subchapter(eir_3_3_2)


def Create_Computer_Resource_Requirements(parent_chapter: CHAPTER, chapter: CHAPTER):
    cr_3_10_1 = CHAPTER(
        title="计算机硬件需求",
        introduction="""本条应描述针对本软件必须使用的计算机硬件的需求（若有）。（若适合）这些需求应包括：各类设备的数量；处理机、存储器、输入/输出设备、辅助存储器、通信/网络设备及所需其他设备的类型、大小、容量和其他所需的特征。"""
    )
    cr_3_10_2 = CHAPTER(
        title="计算机硬件资源使用需求",
        introduction="""本条应描述本软件的计算机硬件资源使用需求（若有），例如：最大允许利用的处理机能力、内存容量、输入/输出设备的能力、辅助存储设备容量和通信/网络设备的能力。这些需求（例如陈述为每一个计算机硬件资源能力的百分比）应包括测量资源使用时所处的条件（若有）。"""
    )
    cr_3_10_3 = CHAPTER(
        title="计算机软件需求",
        introduction="""本条应描述本软件必须使用或必须被并入本软件的计算机软件的需求（若有）。例子包括：操作系统、数据库管理系统、通信/网络软件、实用软件、输入和设备仿真软件、测试软件和制造软件。要列出每一个这样的软件项的正确名称、版本和参考文档。"""
    )
    cr_3_10_4 = CHAPTER(
        title="计算机通信需求",
        introduction="""本条应描述本软件必须使用的计算机通信方面的需求（若有）。例子包括：要连接的地理位置；配置和网络拓扑；传输技术；数据传送速率；网关；要求的系统使用时间；被传送/接收的数据的类型和容量；传送/接收/响应的时间限制；数据量的峰值；以及诊断特性。"""
    )
    chapter.add_subchapter(cr_3_10_1)
    chapter.add_subchapter(cr_3_10_2)
    chapter.add_subchapter(cr_3_10_3)
    chapter.add_subchapter(cr_3_10_4)
