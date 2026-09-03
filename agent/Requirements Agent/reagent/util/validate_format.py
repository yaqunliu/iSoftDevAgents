def _normalize_string_list_field(value):
    """
    教学注释：
    大模型有时会把"本来应该是字符串列表"的字段输出成单个字符串。
    这里先做一次最小容错，把单值整理成列表，避免整条需求链路因为一种常见格式抖动直接报废。
    """

    if isinstance(value, list):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    return value


def _normalize_dict_to_list(value):
    """
    教学注释：
    LLM 经常把 alternative_flows / exception_flows 输出成 dict 格式：
      {"条件A": ["步骤1", "步骤2"], "条件B": ["步骤1"]}
    而校验要求的是 list。这里把 dict 展开成描述性字符串列表：
      ["条件A: 步骤1; 步骤2", "条件B: 步骤1"]
    """
    if not isinstance(value, dict):
        return value
    result = []
    for key, steps in value.items():
        if isinstance(steps, list):
            result.append({"condition": str(key), "steps": [str(s) for s in steps]})
        else:
            result.append(str(steps))
    return result


def normalize_use_case_payload(use_cases):
    """
    接口注释：
    在正式结构校验前，对用户用例结果做轻量归一化。

    设计注释：
    修正 LLM 常见的格式抖动：
    1. 单个字符串被误写成列表字段 → 转为单元素列表
    2. alternative_flows / exception_flows 输出为 dict → 转为 list
    """

    if not isinstance(use_cases, list):
        return use_cases

    normalized_use_cases = []
    list_like_fields = {
        "secondary_actor",
        "preconditions",
        "postconditions",
        "main_flow",
        "alternative_flows",
        "exception_flows",
        "business_rules",
        "assumptions",
        "other_constraints",
    }
    for use_case in use_cases:
        if not isinstance(use_case, dict):
            normalized_use_cases.append(use_case)
            continue
        normalized_use_case = dict(use_case)
        for field in list_like_fields:
            if field not in normalized_use_case:
                continue
            value = normalized_use_case[field]
            # dict → list（alternative_flows / exception_flows 常见）
            if isinstance(value, dict):
                normalized_use_case[field] = _normalize_dict_to_list(value)
            else:
                normalized_use_case[field] = _normalize_string_list_field(value)
        normalized_use_cases.append(normalized_use_case)
    return normalized_use_cases


def validate_use_case_format(use_cases):
    """
    校验用户用例输出是否符合严格的 Use Case 格式规范。
    
    返回:
        (bool, str)
        - True, "OK" 表示通过校验
        - False, 错误信息字符串
    """

    use_cases = normalize_use_case_payload(use_cases)

    required_schema = {
        "use_case_name": str,
        "primary_actor": str,
        "secondary_actor": list,
        "use_case_description": str,
        "trigger": str,
        "preconditions": list,
        "postconditions": list,
        "main_flow": list,
        "alternative_flows": list,
        "exception_flows": list,
        "priority": str,
        "business_rules": list,
        "assumptions": list,
        "other_constraints": list
    }

    # 1️⃣ 顶层必须是 list
    if not isinstance(use_cases, list):
        return False, "Top-level structure must be a list."

    if len(use_cases) == 0:
        return False, "Use case list must not be empty."

    # 2️⃣ 每个元素必须是 dict
    for idx, use_case in enumerate(use_cases):
        if not isinstance(use_case, dict):
            return False, f"Use case at index {idx} is not a dictionary."

        # 3️⃣ 字段必须完全一致（不多不少）
        keys = set(use_case.keys())
        required_keys = set(required_schema.keys())

        if keys != required_keys:
            missing = required_keys - keys
            extra = keys - required_keys
            return False, (
                f"Use case at index {idx} has invalid keys. "
                f"Missing: {missing}, Extra: {extra}"
            )

        # 4️⃣ 字段类型校验
        for field, expected_type in required_schema.items():
            value = use_case[field]

            if not isinstance(value, expected_type):
                return False, (
                    f"Field '{field}' in use case at index {idx} "
                    f"must be of type {expected_type.__name__}."
                )

            # 5️⃣ 验证 list 字段的元素类型
            if expected_type is list:
                for item_idx, item in enumerate(value):
                    # 对于 alternative_flows 和 exception_flows，我们接受两种格式：
                    # - 字符串（旧格式）
                    # - 对象（新格式，包含 condition 和 steps）
                    if field in ['alternative_flows', 'exception_flows']:
                        if not isinstance(item, (str, dict)):
                            return False, (
                                f"Field '{field}' in use case at index {idx} "
                                f"contains invalid element type at position {item_idx}. "
                                f"Expected str or dict, got {type(item).__name__}."
                            )
                    else:
                        # 其他 list 字段（main_flow, preconditions 等）必须是字符串列表
                        if not isinstance(item, str):
                            return False, (
                                f"Field '{field}' in use case at index {idx} "
                                f"contains non-string element at position {item_idx}."
                            )

    return True, "OK"
