import json

def _convert_flow_item(item):
    """
    将流程项转换为字符串格式
    支持两种格式：
    - 字符串格式
    - 对象格式（包含 condition 和 steps）
    """
    if isinstance(item, str):
        return item
    elif isinstance(item, dict):
        condition = item.get('condition', '')
        steps = item.get('steps', [])
        if condition and steps:
            return f"Condition: {condition}\nSteps: " + "; ".join(steps)
        elif condition:
            return f"Condition: {condition}"
        elif steps:
            return "Steps: " + "; ".join(steps)
        else:
            return str(item)
    else:
        return str(item)

def _join_flow_list(flow_list):
    """
    将流程列表连接成字符串，处理对象格式的元素
    """
    converted = [_convert_flow_item(item) for item in flow_list]
    return "; ".join(converted)

class UserCase():
    use_case_name: str
    primary_actor: str
    secondary_actor: list[str]
    use_case_description:str
    preconditions : list[str]
    postconditions: list[str]
    main_flow: list
    alternative_flows: list
    exception_flows: list
    priority: str
    business_rules: list[str]
    assumptions: list[str]
    other_constraints: list[str]

    def __init__(self,input:dict):
        self.main_flow = input['main_flow']
        self.alternative_flows = input['alternative_flows']
        self.assumptions = input['assumptions']
        self.business_rules = input['business_rules']
        self.use_case_name = input['use_case_name']
        self.trigger = input['trigger']
        self.primary_actor = input['primary_actor']
        self.postconditions = input['postconditions']
        self.preconditions = input['preconditions']
        self.exception_flows = input['exception_flows']
        self.priority = input['priority']
        self.secondary_actor = input['secondary_actor']
        self.use_case_description = input['use_case_description']
        self.other_constraints = input['other_constraints']

    def get_usecase(self) -> str:
        """
        返回按照正式顺序排列的用户用例所有属性拼接成的字符串
        顺序: 用例名称 -> 主要参与者 -> 次要参与者 -> 描述 -> 前置条件 -> 后置条件 
             -> 主流程 -> 替代流程 -> 异常流程 -> 优先级 -> 业务规则 -> 假设 -> 其他约束
        """
        result = ''
        result += f"用例名称: {self.use_case_name}\n"
        result += f"主要参与者: {self.primary_actor}\n"
        result += f"次要参与者: {', '.join(self.secondary_actor)}\n"
        result += f"描述: {self.use_case_description}\n"
        result += f"触发器: {self.trigger}\n"
        result += f"前置条件: {', '.join(self.preconditions)}\n"
        result += f"后置条件: {', '.join(self.postconditions)}\n"
        result += f"主流程: {', '.join(self.main_flow)}\n"
        result += f"替代流程: {_join_flow_list(self.alternative_flows)}\n"
        result += f"异常流程: {_join_flow_list(self.exception_flows)}\n"
        result += f"优先级: {self.priority}\n"
        result += f"参考业务规则: {', '.join(self.business_rules)}\n"
        result += f"假设: {', '.join(self.assumptions)}\n"
        result += f"其他约束: {', '.join(self.other_constraints)}\n"
        return result
