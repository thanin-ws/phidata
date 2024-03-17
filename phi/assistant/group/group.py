from uuid import uuid4
from textwrap import dedent
from typing import List, Any, Optional, Dict, Iterator, Union

from pydantic import BaseModel, ConfigDict, field_validator, Field

from phi.assistant.assistant import Assistant
from phi.tools.function import Function
from phi.utils.log import logger, set_log_level_to_debug
from phi.utils.message import get_text_from_message
from phi.utils.tools import get_tool_name
from phi.utils.timer import Timer


class AssistantGroup(BaseModel):
    name: Optional[str] = None

    lead: Optional[Assistant] = None
    members: Optional[List[Assistant]] = None
    reviewer: Optional[Assistant] = None

    # -*- Run settings
    # Run UUID (autogenerated if not set)
    run_id: Optional[str] = Field(None, validate_default=True)
    # Run name
    run_name: Optional[str] = None
    # Metadata associated with this run
    run_data: Optional[Dict[str, Any]] = None

    # If markdown=true, add instructions to format the output using markdown
    markdown: bool = False

    # debug_mode=True enables debug logs
    debug_mode: bool = False
    # monitoring=True logs Assistant runs on phidata.com
    monitoring: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("debug_mode", mode="before")
    def set_log_level(cls, v: bool) -> bool:
        if v:
            set_log_level_to_debug()
            logger.debug("Debug logs enabled")
        return v

    @field_validator("run_id", mode="before")
    def set_run_id(cls, v: Optional[str]) -> str:
        return v if v is not None else str(uuid4())

    @property
    def streamable(self) -> bool:
        return True

    def member_delegation_function(self, member: Assistant, index: int) -> Function:
        def _delegate_task_to_member(task_description: str) -> str:
            return member.run(task_description, stream=False)  # type: ignore

        member_name = member.name.replace(" ", "_").lower() if member.name else f"member_{index}"
        delegation_function = Function.from_callable(_delegate_task_to_member)
        delegation_function.name = f"delegate_task_to_{member_name}"
        delegation_function.description = dedent(
            f"""Use this function to delegate a task to {member_name}

        Args:
            task_description (str): A clear and concise description of the task the assistant should achieve.
        Returns:
            str: The result of the delegated task.
        """
        )
        return delegation_function

    @property
    def leader(self) -> Assistant:
        """Returns the team leader"""

        if self.lead:
            return self.lead

        _delegation_functions = []

        _system_prompt = ""
        if self.members and len(self.members) > 0:
            _system_prompt += "You are the leader of a group of AI Assistants "
            if self.name:
                _system_prompt += f"called '{self.name}'"
        else:
            _system_prompt += "You are an AI Assistant"

        _system_prompt += ". Your goal is to respond to the users message in the best way possible."
        _system_prompt += " This is an important task and must be done correctly.\n\n"

        if self.members and len(self.members) > 0:
            _system_prompt += (
                "Given a user message you can respond directly or delegate tasks to the following assistants depending on their role "
                "and the tools available to them. "
            )
            _system_prompt += "\n\n<assistants>"
            for member_index, member in enumerate(self.members):
                _system_prompt += f"\nAssistant {member_index+1}:\n"

                if isinstance(member, Assistant):
                    if member.name:
                        _system_prompt += f"Name: {member.name}\n"
                    if member.role:
                        _system_prompt += f"Role: {member.role}\n"
                    if member.tools is not None:
                        _tools = []
                        for _tool in member.tools:
                            _tool_name = get_tool_name(_tool)
                            if _tool_name:
                                _tools.append(_tool_name)
                        if len(_tools) > 0:
                            _system_prompt += f"Available tools: {', '.join(_tools)}\n"
                _delegation_functions.append(self.member_delegation_function(member, member_index))
            _system_prompt += "</assistants>\n"

        if self.reviewer is None:
            _system_prompt += "You must always review the responses from the assistants and re-run tasks if the result is not satisfactory."

        return Assistant(
            system_prompt=_system_prompt,
            tools=_delegation_functions,
        )

    def _run(
        self, message: Optional[Union[List, Dict, str]] = None, stream: bool = True, **kwargs: Any
    ) -> Iterator[str]:
        logger.debug(f"*********** Team Run Start: {self.run_id} ***********")

        # Get the team leader
        leader = self.leader

        # Final LLM response after running all tasks
        run_output = ""

        if stream and leader.streamable:
            for chunk in leader.run(message=message, stream=True, **kwargs):
                run_output += chunk if isinstance(chunk, str) else ""
                yield chunk if isinstance(chunk, str) else ""
            yield "\n\n"
            run_output += "\n\n"
        else:
            try:
                leader_response = leader.run(message=message, stream=False, **kwargs)
                if stream:
                    yield leader_response  # type: ignore
                    yield "\n\n"
                else:
                    run_output += leader_response  # type: ignore
                    run_output += "\n\n"
            except Exception as e:
                logger.debug(f"Failed to convert task response to json: {e}")

        if not stream:
            yield run_output
        logger.debug(f"*********** Team Run End: {self.run_id} ***********")

    def run(
        self, message: Optional[Union[List, Dict, str]] = None, stream: bool = True, **kwargs: Any
    ) -> Union[Iterator[str], str, BaseModel]:
        if stream and self.streamable:
            resp = self._run(message=message, stream=True, **kwargs)
            return resp
        else:
            resp = self._run(message=message, stream=False, **kwargs)
            return next(resp)

    def print_response(
        self,
        message: Optional[Union[List, Dict, str]] = None,
        stream: bool = True,
        markdown: bool = False,
        **kwargs: Any,
    ) -> None:
        from phi.cli.console import console
        from rich.live import Live
        from rich.table import Table
        from rich.status import Status
        from rich.progress import Progress, SpinnerColumn, TextColumn
        from rich.box import ROUNDED
        from rich.markdown import Markdown

        if markdown:
            self.markdown = True

        if stream:
            response = ""
            with Live() as live_log:
                status = Status("Working...", spinner="dots")
                live_log.update(status)
                response_timer = Timer()
                response_timer.start()
                for resp in self.run(message, stream=True, **kwargs):
                    response += resp if isinstance(resp, str) else ""
                    _response = Markdown(response) if self.markdown else response

                    table = Table(box=ROUNDED, border_style="blue", show_header=False)
                    if message:
                        table.show_header = True
                        table.add_column("Message")
                        table.add_column(get_text_from_message(message))
                    table.add_row(f"Response\n({response_timer.elapsed:.1f}s)", _response)  # type: ignore
                    live_log.update(table)
                response_timer.stop()
        else:
            response_timer = Timer()
            response_timer.start()
            with Progress(
                SpinnerColumn(spinner_name="dots"), TextColumn("{task.description}"), transient=True
            ) as progress:
                progress.add_task("Working...")
                response = self.run(message, stream=False, **kwargs)  # type: ignore

            response_timer.stop()
            _response = Markdown(response) if self.markdown else response

            table = Table(box=ROUNDED, border_style="blue", show_header=False)
            if message:
                table.show_header = True
                table.add_column("Message")
                table.add_column(get_text_from_message(message))
            table.add_row(f"Response\n({response_timer.elapsed:.1f}s)", _response)  # type: ignore
            console.print(table)