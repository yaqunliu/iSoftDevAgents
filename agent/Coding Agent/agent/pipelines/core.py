from crewai import Task, Crew
from jinja2 import Template


class PipelineStep:

    def __init__(self, *, agent, template_text: str, expected_output: str, output_file: str):
        self.agent = agent
        self.template_text = template_text
        self.expected_output = expected_output
        self.output_file = output_file

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
            verbose=True
        )
        crew.kickoff()

        return task.output.raw
