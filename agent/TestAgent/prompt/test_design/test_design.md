你需要依据需求文档的描述，为指定的功能生成完整的pytest单元测试代码。
你必须完全依据需求来设计测试输入以及测试断言，不要涉及需求未提到的功能，不要遗漏需求的每一点细节。
请在**内部推理过程中**严格按照下面的思维步骤进行思考和决策，但在最终回答里**只输出可直接执行的pytest代码，不要暴露任何中间推理过程或步骤说明**。

【输入说明】
输入如下： 
下面的json中包含多个features，每个feature是功能关联的一组函数，如methods中描述，你需要为每个方法生成多个测试函数。

只关注**controller**层（api http接口层）和**service**层的方法，repository层的方法不需要被测试。

feature内部的方法不需要mock，repository层的方法需要被mock。
{{sut}}

【评审反馈处理】（如果有）
如果这不是第一次生成测试代码，你将收到评审反馈和之前生成的代码：
{{review_feedback}}
上一次生成的代码：
{{previous_code}}

**当收到评审反馈时，你必须**：
1. 仔细阅读评审意见中的所有问题（issues）
2. 针对每个问题，特别是 critical 和 major 级别的问题，进行修正
3. 参考评审意见中的改进建议（suggestion）
4. 保持之前代码中做得好的部分（strengths）
5. 生成改进后的完整测试代码


你需要在**内部思维链中**完成以下步骤：

第 1 步：理解 SUT 与需求语义
1.1 仔细阅读提供的：
被测方法所在的类名、方法名、参数列表、返回值类型；
该方法的业务需求描述（正常流程 + 异常行为）；
该方法依赖的其他服务、仓储、外部系统以及它们的业务规则。
1.2 总结这个方法完成了什么业务行为（一个工作单元 / unit of work）？对调用方来说，什么是“成功”的结果？什么是“失败”的结果？
第 2 步：分析输入空间并划分场景（正常 / 异常 / 边界）
2.1 列出 SUT 的所有输入：
方法参数（包括它们的类型和约束，比如不能为 null、必须 > 0 等）；
隐式输入（例如当前用户状态、数据库中是否已有记录等，可通过 mock 表达）。
2.2 根据业务规则把输入划分为等价类，并识别至少三类场景：
正常场景（Positive）：所有前置条件满足，业务应该成功；
异常场景（Negative/Exception）：某个前置条件不满足或依赖抛出异常，业务应该失败；
边界场景（Boundary）：接近临界值的输入，如数量 = 0、数量 = 最大库存、字符串为空、ID 不存在等。
2.3 为每一类场景选出一两个具有代表性的“样本输入”（参数具体值），保证：
正常场景至少 1 个；
异常场景至少 1 个（如找不到对象、库存不足、非法参数等）；
若需求中存在明显边界条件，则边界场景至少 1 个。
第 3 步：分析依赖与 mock 组合（step）
3.1 对于SUT 在执行过程中会用到的所有依赖（来自前一步的依赖链） 对每个测试场景，思考每个依赖在该场景下应该表现怎样的行为，用“mock 组合表”的方式在脑中枚举：
正常场景：
  依赖通常返回“合理有效”的数据；
  不应抛出异常；
  允许你通过 verify() 来断言它们确实被调用。
异常场景：
  至少一个依赖的行为需要被 mock 成"失败"：
    返回 None；
    返回空集合（[]、{}）；
    抛出业务异常（如 StockNotEnoughException）；
  思考失败发生时，SUT 应该：
    抛出异常？
    返回错误码或 None？
    终止后续依赖调用？
边界场景：
  mock 返回接近边界的数据，如：
    库存 = 请求数量；
    用户刚好不满足某个条件；
  观察是否触发特定分支逻辑。
第 4 步：为每个测试场景构造断言（Assert）
4.1 对每个测试场景，分别从以下三个维度设计预期结果：
返回值断言：
  正常场景：使用 assert 检查返回对象的关键字段是否符合业务期望（如 user_id、product_id、qty、状态等）；
  异常场景：使用 pytest.raises() 检查是否抛出预期异常类型和消息。
副作用 / 状态变化断言（通过 mock 交互体现）：
  使用 mock.assert_called_once()、mock.assert_called_with() 检查依赖是否被调用（或不被调用）；
  使用 mock.call_args 或 mock.call_args_list 捕获传入依赖的方法参数并检查其字段。
调用顺序断言（可选）：
  如果业务对顺序敏感，检查 mock.call_args_list 或使用 mock.mock_calls 验证依赖调用顺序；
  例如：先 check_stock，再 deduct_stock，再 save，再 notify。
4.2 确保每个测试场景的断言是"可观察"的，不依赖于私有字段或内部实现细节：
不要直接断言私有状态；
更侧重于返回值、mock 交互、调用次数和顺序。
第 5 步：把场景 + mock + oracle 映射为 pytest 测试函数
5.1 为每个场景设计一个清晰的测试函数名，建议格式：
test_methodName_when前置条件_should期望结果
  例如：test_place_order_when_stock_is_enough_should_create_order_and_notify_user
5.2 每个测试函数内分成 3 个逻辑区块（使用注释标识）：
# Arrange：
  使用 pytest 的 monkeypatch 或 unittest.mock 配置所有 mock 的行为；
  构造输入参数；
  不要遗漏任何依赖的必要模拟。
# Act：
  调用被测方法（SUT）并捕获返回值或异常。
# Assert：
  对返回值进行 assert 断言；
  使用 mock.assert_called_with() 或 mock.call_count 检查依赖调用；
  对于异常测试，使用 pytest.raises() 捕获预期异常。
5.3 思考是否需要 pytest fixtures 来提供公共的测试数据或初始化逻辑。

第 6 步：生成完整的 pytest 代码文件
6.1 在文件开头导入必要的模块：
  import pytest
  from unittest.mock import Mock, MagicMock, patch, call
  导入被测试的类和相关依赖
6.2 如果需要，定义 pytest fixtures（使用 @pytest.fixture 装饰器）
6.3 为每个测试场景编写独立的测试函数（以 test_ 开头）
6.4 确保代码可以直接运行，包含所有必要的 import 语句
6.5 代码要符合 PEP 8 规范，使用合理的缩进和命名
6.6 每个测试函数前添加简洁的 docstring 说明测试目的

【输出格式】
直接输出完整的 Python pytest 代码，格式如下：

```python
"""
测试模块描述
"""
import pytest
from unittest.mock import Mock, MagicMock, patch

# 导入被测试的类和依赖
from module_path import TargetClass, DependencyClass

# Fixtures（如果需要）
@pytest.fixture
def fixture_name():
    """Fixture 说明"""
    # 设置代码
    return test_data

# 测试类（可选，用于组织相关测试）
class TestTargetClass:
    """测试 TargetClass 的测试类"""
    
    def test_method_when_condition_should_result(self):
        """测试方法在某条件下应该产生某结果"""
        # Arrange
        mock_dependency = Mock()
        mock_dependency.method.return_value = expected_value
        target = TargetClass(mock_dependency)
        
        # Act
        result = target.method(params)
        
        # Assert
        assert result == expected_result
        mock_dependency.method.assert_called_once_with(expected_args)
```

**重要提示**：
- 输出的代码必须是完整的、可直接运行的 Python 文件
- 不要包含 "```python" 标记或其他 markdown 格式
- 不要输出解释性文字，只输出代码
- 确保所有 import 语句正确
- 确保 mock 对象正确配置
- 每个测试函数必须独立，不依赖其他测试的执行顺序