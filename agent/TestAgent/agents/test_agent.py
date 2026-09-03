from crewai import Agent
from crewai import LLM

from config import config
from tools.code_search import CodeSearchTool
from tools.run_py_test import RunProjectGeneratedTestsTool
from tools.write_python_file import WriteCodeFileTool

llm = LLM(
    model=config.config['llm']['model'],
    api_key=config.config['llm']['api_key'],
    base_url=config.config['llm']['base_url']
)


def create_test_architect():
    return Agent(
        role="Test Architect",
        goal="""
            Unit testing of the entire system is difficult, as you need to break it down into several functional modules. 
            Each functional module contains several features, and each feature contains several methods. 
            They have dependencies and work together to complete a set of functional requirements. 
            The partitioned features will serve as the smallest unit of work, and testers will generate unit tests for all methods in a feature each time, ensuring that each feature is independent and contains sufficient contextual information. 
            Output the divided functional modules as the test plan.
        """,
        backstory="A testing architect who excels in breaking down the entire project and specifying testing plans based on the principle of high cohesion and low coupling.",
        llm=llm
    )


def create_test_designer():
    return Agent(
        role="Test Designer",
        goal="Generate complete and executable pytest unit test code based on requirement descriptions. The code must be directly runnable, follow best practices, and cover all scenarios.",
        backstory="An experienced software testing engineer who writes high-quality pytest test code for each functional requirement, including proper mocking, assertions, and test organization.",
        llm=llm,
        tools=[
            CodeSearchTool(),
            WriteCodeFileTool(),
            RunProjectGeneratedTestsTool()
        ]
    )


def create_test_reviewer():
    return Agent(
        role="Test Reviewer",
        goal="""
            Review generated pytest test code comprehensively to ensure quality, completeness, and correctness.
            Check requirement coverage, code quality, mock usage, assertion completeness, and executability.
            Provide constructive feedback with specific, actionable suggestions for improvement.
            Approve tests only when they meet high-quality standards (score >= 80 and no critical issues).
        """,
        backstory="A senior QA expert and code reviewer with deep expertise in Python testing frameworks, particularly pytest. Excels at identifying test gaps, code smells, and potential runtime issues. Known for thorough yet constructive reviews that elevate test quality.",
        llm=llm,
        verbose=True
    )





