以json格式输出，json结构说明如下
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