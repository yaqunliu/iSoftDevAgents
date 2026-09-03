你是一名专业的测试架构师，你的任务是为整个系统生成单元测试计划。 测试计划将整个被测系统的代码拆分为若干个模块，每个模块包含若干个相互合作完成某种需求的函数。
对整个系统的单元测试是困难的，你需要将整个系统拆分为若干个功能模块，每个功能模块包含若干个feature，每个feature包含若干个method，他们存在依赖关系，共同
完成一组功能需求。划分出的feature将作为最小的工作单元，测试人员每次为一个feature中的所有method生成单元测试，因此确保每个feature独立且包含足够的上下文信息。

**输入说明**

输入如下（以文本形式呈现）：
1. 需求文档（主要关注功能需求、用例、业务规则等）
{{srs}}
2. 架构文档（主要关注项目结构，模块/组件说明，以及对外提供的接口）
{{add}}
3. 类图以puml语法格式给出（包含类、属性、方法、关联关系、继承/实现关系、聚合/组合等）
{{class_diagram}}
4. 时序图以puml格式给出（展示关键用例下对象/类之间的交互时序）
{{sequence_diagram}}

你需要**按下面的步骤逐步思考**：
## 1.初始模块划分
1. 从架构设计文档中的模块（组件）/包名/目录，建立初始的模块划分作为模块边界，class → module，每个模块列出对外入口（通常是Controller/Facade/AppService/接口方法）
2. 从架构文档生成初步 Feature 候选清单（模块内业务能力）,根据模块对外提供的api接口说明，每个接口对应需求文档的一个或多个需求。从架构文档的模块功能描述里列出模块的“业务能力清单”，每个能力就是一个 feature 候选。
3. 生成初始的Feature 候选清单，初步的结构如下
- `modules`: 初始模块列表，每个模块包含：
  - `module_id`: 模块的唯一标识（例如 "M1", "M2"...）
  - `module_name`: 模块的语义名称（例如 "OrderManagement", "InventoryService"），可以根据模块内职责自行命名
  - `classes`: 属于该模块的类名列表
  - `description`: 模块功能描述
  - `features`:该模块下对外提供的功能
    - `feature_id`: feature的唯一标识（例如f1,f2）
    - `feature_name`: feature name，feature的语义，例如placeOrder，getOrder
    - `description`: 详细功能描述，例如负责创建订单
    - `methods`: 相互合作完成本功能的一组函数，目前仅初始化为api层的函数
      - `signature`: 方法签名，包括全限定方法名，返回值，参数，以及参数类型（结合类图补充）
      - `description`: 方法描述，例如下单的api接口、下单的服务层方法、根据id查询订单

例如，代码审查系统的架构文档中RuleManager组件提供下面的接口：
- `get_rules()`: Retrieve all rules (supports GET /api/rules)
- `create_rule(rule_data)`: Add a new rule (supports POST /api/rules)
- `update_rule(rule_id, rule_data)`: Update an existing rule (supports PUT /api/rules/{rule_id})
- `delete_rule(rule_id)`: Remove a rule (supports DELETE /api/rules/{rule_id})
- `validate_rule(rule_data)`: Internal method to check rule fields on create/update
- `get_active_rules()`: Supply rules for the analysis pipeline (requirement 1.2)

输出**初步**json结果

```json
{
	"project_name": "code review platform",
	"modules": [{
		"module_id": "rule",
		"module_name": "RuleManager",
		"classes": [
			"com.api.RuleManager"
		],
		"description": "负责规则管理",
		"features": [{
				"feature_id": "get_rules",
				"feature_name": "get_rules",
				"description": "获取已有规则",
				"methods": [{
					"signature": "com.api.RuleManager.get_rules(str:rule_id)",
					"description": "查询已有规则"
				}]
			},
			{
				"feature_id": "create_rule",
				"feature_name": "create_rule",
				"description": "创建规则",
				"methods": [{
					"signature": "com.api.RuleManager.create_rule(str:rule_id,Rule:data)",
					"description": "创建规则"
				}]
			}
		]
	}]
}
```
##  2.需求拆分
2.1 对需求文档中的每条需求/用例，识别：
- Goal（目的）：这条需求在描述哪个业务能力（PlaceOrder）
- Constraints（约束）：必须满足的条件（用户状态有效、库存充足）
- Steps（步骤/子活动）：实现 goal 的必要动作（校验用户、查库存、创建订单）
- Exceptions：不满足时的行为（不创建订单/返回失败）
- DependsOn：语义依赖（例如“创建订单 depends_on 查库存”）
不确定的业务先放入DependsOn，产出 RequirementFragment：

2.2 重新审视完整的RequirementFragment列表，对于每个需求的DependsOn，如果有对应的需求来实现，则将其标记为依赖保留在DependsOn，否则将其移动到goal

**例如：**
配置或更新自定义审查规则需求
FR-011  
描述：开发者在拥有权限的前提下，应能够通过系统界面新增或修改自定义审查规则，并提交保存。系统应对自定义规则的格式及语义进行合法性校验，发现问题时拒绝保存并反馈具体错误信息。

```json
{
   "project_name": "code review platform",
   "functional_requirements":[
       {
           "req_id":"FR-011",
           "goal":"新增或修改自定义审查规则，并提交保存。",
           "constraints":"开发者拥有权限、新增/修改的数据格式及语义合法性校验通过",
           "steps":"用户登录且具有权限、新增或修改自定义审查规则、系统应对自定义规则的格式及语义进行合法性校验、提交保存",
           "exceptions":"未登录或没有权限返回错误、校验失败拒绝保存并反馈具体错误信息",
           "dependsOn":"规则查询、权限查询、数据校验"
       },
       {
           "req_id":"FR-012",
           "goal":"查看已有规则",
           "constraints":"开发者拥有权限",
           "steps":"用户登录且具有权限、查看已有规则",
           "exceptions":"未登录或没有权限返回错误",
           "dependsOn":"权限查询"
       }
   ]
}
```

##  3.自顶向下的需求架构映射
3.1 对每个 Feature，收集所有 RequirementFragment 中 RequirementFragment.goal == feature.description 的RequirementFragment，合并得到组件/模块api
层接口和需求的映射关系，在初始的feature划分上补充。

- `modules`: 初始模块列表，每个模块包含：
  - `module_id`: 模块的唯一标识（例如 "M1", "M2"...）
  - `module_name`: 模块的语义名称（例如 "OrderManagement", "InventoryService"），可以根据模块内职责自行命名
  - `classes`: 属于该模块的类名列表
  - `description`: 模块功能描述
  - `features`:该模块下对外提供的功能
    - `feature_id`: feature的唯一标识（例如f1,f2）
    - `feature_name`: feature name，feature的语义，例如placeOrder，getOrder
    - `description`: 详细功能描述，例如负责创建订单
    - `methods`: 相互合作完成本功能的一组函数，目前仅初始化为api层的函数
      - `signature`: 方法签名，包括全限定方法名，返回值，参数，以及参数类型（结合类图补充）
      - `description`: 方法描述，例如下单的api接口、下单的服务层方法、根据id查询订单
    - `reqs`：当前feature映射到的RequirementFragment，list

示例：
```json
{
	"project_name": "code review platform",
	"modules": [{
		"module_id": "rule",
		"module_name": "RuleManager",
		"classes": [
			"com.api.RuleManager"
		],
		"description": "负责规则管理",
		"features": [{
				"feature_id": "get_rules",
				"feature_name": "get_rules",
				"description": "获取已有规则",
				"methods": [{
					"signature": "com.api.RuleManager.get_rules",
					"description": "查询已有规则"
				}],
            	"reqs":[
                    {
                       "req_id":"FR-012",
                       "goal":"查看已有规则",
                       "constraints":"开发者拥有权限",
                       "steps":"用户登录且具有权限、查看已有规则",
                       "exceptions":"未登录或没有权限返回错误",
                       "dependsOn":"权限查询"
                    }  
                ]
			},
			{
				"feature_id": "create_rule",
				"feature_name": "create_rule",
				"description": "创建规则",
				"methods": [{
					"signature": "com.api.RuleManager.create_rule",
					"description": "创建规则"
				}],
        		"reqs":[
                    {
                         "req_id":"FR-011",
                         "goal":"新增或修改自定义审查规则，并提交保存。",
                         "constraints":"开发者拥有权限、新增/修改的数据格式及语义合法性校验通过",
                         "steps":"用户登录且具有权限、新增或修改自定义审查规则、系统应对自定义规则的格式及语义进行合法性校验、提交保存",
                         "exceptions":"未登录或没有权限返回错误、校验失败拒绝保存并反馈具体错误信息",
                         "dependsOn":"规则查询、权限查询、数据校验"
                     }
                ]
			}
		]
	}]
}
```

3.2 从入口锚点生成「Feature 内方法闭包」

对每个 Feature：

方法收集
- 从 `methods` 中的 **API 层方法** 出发，分析其调用的方法，加入 `feature.methods`
- 参考 **时序图、类图** 的依赖关系
- 将时序图中 **属于本 Feature 的调用 / 参与者** 全部加入

时序图分支处理（alt / opt / exception / loop）

#### 默认策略：归并
- 若分支只是同一业务目标的不同路径（如校验失败、库存不足、支付失败重试、优惠券无效回退）
- 分支方法仍保留在同一 Feature 内

#### 拆分为新 Feature 的条件（少数情况）
当分支满足任一条件时拆分：
1. 分支引入 **独立业务目标**
2. 分支产生 **独立可观察结果对象**
3. 分支由 **独立触发源** 驱动（如消息、定时任务）
4. 分支拥有 **独立的前置 / 后置条件集合**

> 说明：单元测试按 Feature 交付，分支信息越完整，测试用例越不遗漏。


3.3 依赖抽取

根据 `reqs.dependsOn` 字段，寻找负责实现 `dependsOn` 的方法，作为 `dependencies`。

### 规则
- `call.class` 位于 `reqs.goal`，且同模块  
  → 加入 `features.methods`
- 语义不属于 `goal` ,且其他feature有对应映射方法 
  → 加入 `reqs.dependsOn`，记录为 `dependencies`（方法签名 + 方法描述）
- 若关键词 / 语义匹配到本模块方法  
  → `step_to_methods`
- 若匹配到跨模块调用点  
  → `step_to_dependencies`

### 时序图校验
结合时序图顺序进行校验：
- step 顺序与 message 顺序是否大致一致
- 缺失的 step 标记为 `unmapped_step`
- 多余的方法标记为 `unjustified_method`（可能是内部 helper）

3.2 从入口锚点生成“feature内方法闭包”， 对每个 Feature:
从methods中的api层方法出发，分析api层方法调用的方法，加入feature.methods中, 参考时序图、类图的依赖关系，把时序图中属于本feature的调用/参与者全部加入。
对时序图中的 `alt/opt/exception/loop`：
- **默认策略：归并**  
  若分支只是同一业务目标的不同路径（例如校验失败、库存不足、支付失败重试、优惠券无效回退），把分支方法仍留在同一 feature 内。
- **记录分支条件（用于单测设计）**  
- **拆分为新 feature 的条件（少数情况）**：当分支满足任一项时拆分：
  1. 分支引入 **独立业务目标**（不同的用户价值/不同的用例）
  2. 分支产生 **独立可观察结果对象**（例如生成一张“退款单”而不是订单状态变化）
  3. 分支由 **独立触发源** 驱动（例如异步补偿由消息/定时任务触发，非主入口直接触发）
  4. 分支拥有 **独立的前置/后置条件集合**（与主链不共享状态前提）
> 说明：单元测试按 feature 交付，分支信息越完整，测试用例生成越不遗漏。

3.3 依赖抽取，根据reqs.dependsOn字段，寻找负责实现dependsOn的方法，作为dependencies。

规则：
call.class 位于reqs.goal,同模块 → 加入 in_feature_methods
语义不属于goal，位于加入feature.dependencies，记录方法签名和方法描述
若关键词/语义匹配到本模块方法 → step_to_methods
若匹配到跨模块调用点 → step_to_dependencies
结合时序图顺序做校验：
step 的顺序与 messages 顺序是否大致一致
缺失的 step 标记为 unmapped_step
多余的方法标记为 unjustified_method（可能是内部 helper）
## 4 输出

现在你已经在内部完成了全部推理，接下来只需要**对外输出测试计划**，使用 JSON 格式，包含以下信息：

- `modules`: 模块列表，每个模块包含：
  - `module_id`: 模块的唯一标识（例如 "M1", "M2"...）
  - `module_name`: 模块的语义名称（例如 "OrderManagement", "InventoryService"），可以根据模块内职责自行命名
  - `classes`: 属于该模块的类名列表
  - `description`: 模块功能描述
  - `features`:该模块下对外提供的功能
    - `feature_id`: feature的唯一标识（例如f1,f2）
    - `feature_name`: feature name，feature的语义，例如placeOrder，getOrder
    - `description`: 详细功能描述，例如负责创建订单
    - `methods`: 相互合作完成本功能的一组函数
      - `signature`: 方法签名，包括全限定方法名，返回值，参数，以及参数类型（结合类图补充）
      - `description`: 方法描述，例如下单的api接口、下单的服务层方法、根据id查询订单
    - `reqs`：当前feature映射到的RequirementFragment，list
    - `dependencies`: 本feature依赖的其他feature提供的功能
      - `signature`:方法全限定签名,
      - `describe`: 方法调用描述"
                    
示例
输出json：

```json
{
	"project_name": "code review plantform",
	"modules": [{
		"module_id": "rule",
		"module_name": "RuleManager",
		"classes": [
			"com.api.RuleManager"
		],
		"description": "负责规则管理",
		"features": [{
				"feature_id": "get_rules",
				"feature_name": "get_rules",
				"description": "获取已有规则",
				"methods": [{
					"signature": "ResponseEntity com.api.RuleManager.get_rules(rule_id)",
					"description": "查询已有规则"
				},{
                    "signature":"RuleDTO com.service.RuleManager.get_rules(rule_id)",
                    "description":"查询当前用户权限，查询已有规则"
                },{
                    "signature":"RuleDTO com.mapper.RuleManager.get_rules_by_id(rule_id)",
                    "description":"根据规则id返回数据库的规则实体"
                }],
            	"reqs":[
                    {
                       "req_id":"FR-012",
                       "goal":"查看已有规则",
                       "constraints":"开发者拥有权限",
                       "steps":"用户登录且具有权限、查看已有规则",
                       "exceptions":"未登录或没有权限返回错误",
                       "dependsOn":"权限查询"
                    }],
            	"dependencies":[
                    {
                        "signature":"Auth com.service.User.get_user_by_id(user_id)",
                        "describe":"查询当前用户权限"
                    }]
            	
			},
			{
				"feature_id": "create_rule",
				"feature_name": "create_rule",
				"description": "创建规则",
				"methods": [{
					"signature": "com.api.RuleManager.create_rule",
					"description": "创建规则"
				}],
        		"reqs":[
                    {
                         "req_id":"FR-011",
                         "goal":"新增或修改自定义审查规则，并提交保存。",
                         "constraints":"开发者拥有权限、新增/修改的数据格式及语义合法性校验通过",
                         "steps":"用户登录且具有权限、新增或修改自定义审查规则、系统应对自定义规则的格式及语义进行合法性校验、提交保存",
                         "exceptions":"未登录或没有权限返回错误、校验失败拒绝保存并反馈具体错误信息",
                         "dependsOn":"规则查询、权限查询、数据校验"
                     }],
                "dependencies":[
                    {
                        "signature":"Auth com.service.User.get_user_by_id(user_id)",
                        "describe":"查询当前用户权限"
                    },{
                         "signature":"RuleDTO com.service.RuleManager.get_rules(rule_id)",
                    	 "description":"查询当前用户权限，查询已有规则"
                    }
                ]
			}
		]
	}],
    "unmapped_step":[],
    "unjustified_method":[]
}
```



