import asyncio
import json
import time
from logging import LoggerAdapter
from types import MappingProxyType
from typing import Callable, cast

from openhands.controller import AgentController
from openhands.controller.agent import Agent
from openhands.controller.replay import ReplayManager
from openhands.controller.state.state import State
from openhands.core.config import AgentConfig, LLMConfig, OpenHandsConfig
from openhands.core.exceptions import AgentRuntimeUnavailableError
from openhands.core.logger import OpenHandsLoggerAdapter
from openhands.core.schema.agent import AgentState
from openhands.events.action import ChangeAgentStateAction, MessageAction
from openhands.events.event import Event, EventSource
from openhands.events.stream import EventStream
from openhands.integrations.provider import (
    CUSTOM_SECRETS_TYPE,
    PROVIDER_TOKEN_TYPE,
    ProviderHandler,
)
from openhands.mcp import add_mcp_tools_to_agent
from openhands.memory.memory import Memory
from openhands.microagent.microagent import BaseMicroagent
from openhands.runtime import get_runtime_cls
from openhands.runtime.base import Runtime
from openhands.runtime.impl.remote.remote_runtime import RemoteRuntime
from openhands.security import SecurityAnalyzer, options
from openhands.storage.data_models.user_secrets import UserSecrets
from openhands.storage.files import FileStore
from openhands.utils.async_utils import EXECUTOR, call_sync_from_async
from openhands.utils.shutdown_listener import should_continue

WAIT_TIME_BEFORE_CLOSE = 90
WAIT_TIME_BEFORE_CLOSE_INTERVAL = 5

from dataclasses import dataclass, field
from typing import List, Dict
from openhands.core.config.mcp_config import MCPConfig, OpenHandsMCPConfigImpl
from openhands.core.config.condenser_config import (
    CondenserPipelineConfig,
)
from openhands.server.session.schemas import SessionParameters

@dataclass
class LLMConfig:
    model: str = ''
    api_key: str | None = None
    base_url: str | None = None
    # ... 기타 LLM 관련 설정

@dataclass
class SecurityConfig:
    confirmation_mode: str = 'auto'
    security_analyzer: str | None = None

@dataclass
class SandboxConfig:
    base_container_image: str | None = None
    runtime_container_image: str | None = None

@dataclass
class AgentSettings:
    """최종적으로 에이전트 실행에 필요한 모든 설정을 담는 컨테이너"""
    agent_cls: type
    max_iterations: int
    max_budget_per_task: float | None
    llm_config: LLMConfig
    security_config: SecurityConfig
    sandbox_config: SandboxConfig
    mcp_config: MCPConfig # MCPConfig도 dataclass로 정의되었다고 가정
    condenser_config: CondenserPipelineConfig | None = None
    # ... 기타 필요한 설정 그룹


# @dataclass
# class AgentSettings:
#     """최종적으로 에이전트 실행에 필요한 모든 설정을 담는 컨테이너"""
#     agent_cls: type
#     max_iterations: int
#     max_budget_per_task: float | None
#     llm_config: LLMConfig
#     security_config: SecurityConfig
#     sandbox_config: SandboxConfig
#     mcp_config: MCPConfig # MCPConfig도 dataclass로 정의되었다고 가정
#     condenser_config: CondenserPipelineConfig | None = None
#     # ... 기타 필요한 설정 그룹

# def compose_session_params(git_provider_tokens: object | None, custom_secrets: CUSTOM_SECRETS_TYPE | None , selected_repository: str | None , selected_branch: str | None) -> SessionParameters:
#     return SessionParameters(
#         git_provider_tokens=git_provider_tokens,
#         custom_secrets=custom_secrets,
#         selected_repository=selected_repository,
#         selected_branch=selected_branch,
#     )

@dataclass
class RuntimeParams:
    runtime_name: str
    config: OpenHandsConfig
    agent: Agent

def compose_runtime_params(config: OpenHandsConfig, agent: Agent):
    runtime_name = config.runtime
    return RuntimeParams(
        runtime_name=runtime_name,
        config=config,
        agent=agent,
    )

# Part 1: Data Structures (새 dataclass 추가)
@dataclass
class MemoryParams:
    event_stream: EventStream
    runtime: Runtime
    selected_repository: str | None
    repo_directory: str | None
    conversation_instructions: str | None
    custom_secrets_descriptions: dict[str, str]

@dataclass
class ControllerParams:
    agent: Agent
    confirmation_mode: bool
    max_iterations: int
    max_budget_per_task: float | None
    agent_to_llm_config: dict[str, LLMConfig] | None
    agent_configs: dict[str, AgentConfig] | None
    replay_events: list[Event] | None

# Part 2: Data Transformation Logic (stateless 빌더 함수)
def build_env_vars(custom_secrets: CUSTOM_SECRETS_TYPE | None) -> dict:
    """환경 변수 데이터를 변환합니다."""
    handler = UserSecrets(custom_secrets or {})
    return handler.get_env_vars()

# Part 3: Object Assembly Logic (FP Composition 함수)
def compose_security_analyzer(analyzer_name: str | None, event_stream: EventStream) -> SecurityAnalyzer | None:
    """[FP-Style] SecurityAnalyzer를 조립합니다."""
    if analyzer_name:
        return options.SecurityAnalyzers.get(analyzer_name, SecurityAnalyzer)(event_stream)
    return None

async def compose_runtime(params: RuntimeParams, session_params: SessionParameters) -> Runtime:
    """[FP-Style] Runtime을 조립합니다."""
    # 원본 _create_runtime 로직 재사용/적응
    custom_secrets_handler = UserSecrets(session_params.custom_secrets or {})
    env_vars = build_env_vars(session_params.custom_secrets)  # 빌더 호출

    runtime_cls = get_runtime_cls(params.runtime_name)
    # ... (RemoteRuntime vs. 다른 경우 분기 로직 그대로)
    runtime = runtime_cls(...)  # 세부 생성
    await runtime.connect()
    await runtime.clone_or_init_repo(...)  # 등등
    return runtime

async def compose_memory(params: MemoryParams) -> Memory:
    """[FP-Style] Memory를 조립합니다."""
    memory = Memory(
        event_stream=params.event_stream,
        sid=...,  # sid 등 필요한 값 전달
        status_callback=...,
    )
    memory.set_runtime_info(params.runtime, params.custom_secrets_descriptions)
    memory.set_conversation_instructions(params.conversation_instructions)
    # ... (microagents 로딩 등 원본 로직)
    return memory

def compose_controller(params: ControllerParams, event_stream: EventStream, ...) -> AgentController:
    """[FP-Style] AgentController를 조립합니다."""
    # 원본 _create_controller 로직 재사용
    initial_state = ...  # 상태 복원
    controller = AgentController(
        agent=params.agent,
        confirmation_mode=params.confirmation_mode,
        # ... 나머지 파라미터
    )
    return controller

class AgentSession:
    """Represents a session with an Agent

    Attributes:
        controller: The AgentController instance for controlling the agent.
    """

    sid: str
    user_id: str | None
    event_stream: EventStream
    file_store: FileStore
    controller: AgentController | None = None
    runtime: Runtime | None = None
    security_analyzer: SecurityAnalyzer | None = None
    memory: Memory | None = None
    _starting: bool = False
    _started_at: float = 0
    _closed: bool = False
    loop: asyncio.AbstractEventLoop | None = None
    logger: LoggerAdapter

    def __init__(
        self,
        sid: str,
        file_store: FileStore,
        status_callback: Callable | None = None,
        user_id: str | None = None,
    ) -> None:
        """Initializes a new instance of the Session class

        Parameters:
        - sid: The session ID
        - file_store: Instance of the FileStore
        """

        self.sid = sid
        self.event_stream = EventStream(sid, file_store, user_id)
        self.file_store = file_store
        self._status_callback = status_callback
        self.user_id = user_id
        self.logger = OpenHandsLoggerAdapter(
            extra={'session_id': sid, 'user_id': user_id}
        )

    async def start(
        self,
        # runtime_name: str,
        # config: OpenHandsConfig,
        # agent: Agent,
        # max_iterations: int,
        # git_provider_tokens: PROVIDER_TOKEN_TYPE | None = None,
        # custom_secrets: CUSTOM_SECRETS_TYPE | None = None,
        # max_budget_per_task: float | None = None,
        # agent_to_llm_config: dict[str, LLMConfig] | None = None,
        # agent_configs: dict[str, AgentConfig] | None = None,
        # selected_repository: str | None = None,
        # selected_branch: str | None = None,
        # initial_message: MessageAction | None = None,
        # conversation_instructions: str | None = None,
        # replay_json: str | None = None,
        config: OpenHandsConfig,
        agent: Agent,
        settings: AgentSettings,
        params: SessionParameters
    ) -> None:
        """Starts the Agent session
        Parameters:
        - runtime_name: The name of the runtime associated with the session
        - config:
        - agent:
        - max_iterations:
        - max_budget_per_task:
        - agent_to_llm_config:
        - agent_configs:
        """
        if self.controller or self.runtime:
            raise RuntimeError(
                'Session already started. You need to close this session and start a new one.'
            )

        if self._closed:
            self.logger.warning('Session closed before starting')
            return

        self._starting = True
        started_at = time.time()
        self._started_at = started_at

        finished = False  # For monitoring
        runtime_connected = False
        restored_state = False


        custom_secrets_handler = UserSecrets(
            custom_secrets=params.custom_secrets if params.custom_secrets else {}
        )

        try:
            self._create_security_analyzer(config.security.security_analyzer)
            # 1. Security Analyzer 조립
            self.security_analyzer = compose_security_analyzer(config.security.security_analyzer, self.event_stream)

            runtimeParams = compose_runtime_params(config, agent)
            exit(0)
            runtime_connected = await self._create_runtime(runtimeParams, params)
            runtime_connected = await compose_runtime(runtime_params, params)

            # runtime_connected = await self._create_runtime(
            #     runtime_name=runtime_name,
            #     config=config,
            #     agent=agent,
            #     git_provider_tokens=git_provider_tokens,
            #     custom_secrets=custom_secrets,
            #     selected_repository=selected_repository,
            #     selected_branch=selected_branch,
            # )

            repo_directory = None
            if self.runtime and runtime_connected and selected_repository:
                repo_directory = selected_repository.split('/')[-1]

            if git_provider_tokens:
                provider_handler = ProviderHandler(provider_tokens=git_provider_tokens)
                await provider_handler.set_event_stream_secrets(self.event_stream)

            if custom_secrets:
                custom_secrets_handler.set_event_stream_secrets(self.event_stream)

            # 3. Memory 조립
            memory_params = MemoryParams(
                event_stream=self.event_stream,
                runtime=self.runtime,
                # ... 나머지 값 채우기
            )

            # self.memory = await self._create_memory(
            #     selected_repository=selected_repository,
            #     repo_directory=repo_directory,
            #     conversation_instructions=conversation_instructions,
            #     custom_secrets_descriptions=custom_secrets_handler.get_custom_secrets_descriptions(),
            # )
            self.memory = await compose_memory(memory_params)

            # NOTE: this needs to happen before controller is created
            # so MCP tools can be included into the SystemMessageAction
            if self.runtime and runtime_connected and agent.config.enable_mcp:
                await add_mcp_tools_to_agent(agent, self.runtime, self.memory)

            if replay_json:
                initial_message = self._run_replay(
                    initial_message,
                    replay_json,
                    agent,
                    config,
                    max_iterations,
                    max_budget_per_task,
                    agent_to_llm_config,
                    agent_configs,
                )
            else:
                # 4. Controller 조립
                controller_params = ControllerParams(
                    agent=agent,
                    confirmation_mode=config.security.confirmation_mode,
                    # ... 나머지 값
                )
                # self.controller, restored_state = self._create_controller(
                #     agent,
                #     config.security.confirmation_mode,
                #     max_iterations,
                #     max_budget_per_task=max_budget_per_task,
                #     agent_to_llm_config=agent_to_llm_config,
                #     agent_configs=agent_configs,
                # )
                self.controller, restored_state = compose_controller(controller_params, self.event_stream, ...)



            if not self._closed:
                if initial_message:
                    self.event_stream.add_event(initial_message, EventSource.USER)
                    self.event_stream.add_event(
                        ChangeAgentStateAction(AgentState.RUNNING),
                        EventSource.ENVIRONMENT,
                    )
                else:
                    self.event_stream.add_event(
                        ChangeAgentStateAction(AgentState.AWAITING_USER_INPUT),
                        EventSource.ENVIRONMENT,
                    )
            finished = True
        finally:
            self._starting = False
            success = finished and runtime_connected
            duration = time.time() - started_at

            log_metadata = {
                'signal': 'agent_session_start',
                'success': success,
                'duration': duration,
                'restored_state': restored_state,
            }
            if success:
                self.logger.info(
                    f'Agent session start succeeded in {duration}s', extra=log_metadata
                )
            else:
                self.logger.error(
                    f'Agent session start failed in {duration}s', extra=log_metadata
                )

    async def close(self) -> None:
        """Closes the Agent session"""
        if self._closed:
            return
        self._closed = True
        while self._starting and should_continue():
            self.logger.debug(
                f'Waiting for initialization to finish before closing session {self.sid}'
            )
            await asyncio.sleep(WAIT_TIME_BEFORE_CLOSE_INTERVAL)
            if time.time() <= self._started_at + WAIT_TIME_BEFORE_CLOSE:
                self.logger.error(
                    f'Waited too long for initialization to finish before closing session {self.sid}'
                )
                break
        if self.event_stream is not None:
            self.event_stream.close()
        if self.controller is not None:
            self.controller.save_state()
            await self.controller.close()
        if self.runtime is not None:
            EXECUTOR.submit(self.runtime.close)
        if self.security_analyzer is not None:
            await self.security_analyzer.close()

    def _run_replay(
        self,
        initial_message: MessageAction | None,
        replay_json: str,
        agent: Agent,
        config: OpenHandsConfig,
        max_iterations: int,
        max_budget_per_task: float | None,
        agent_to_llm_config: dict[str, LLMConfig] | None,
        agent_configs: dict[str, AgentConfig] | None,
    ) -> MessageAction:
        """
        Replays a trajectory from a JSON file. Note that once the replay session
        finishes, the controller will continue to run with further user instructions,
        so we still need to pass llm configs, budget, etc., even though the replay
        itself does not call LLM or cost money.
        """
        assert initial_message is None
        replay_events = ReplayManager.get_replay_events(json.loads(replay_json))
        self.controller, _ = self._create_controller(
            agent,
            config.security.confirmation_mode,
            max_iterations,
            max_budget_per_task=max_budget_per_task,
            agent_to_llm_config=agent_to_llm_config,
            agent_configs=agent_configs,
            replay_events=replay_events[1:],
        )
        assert isinstance(replay_events[0], MessageAction)
        return replay_events[0]

    def _create_security_analyzer(self, security_analyzer: str | None) -> None:
        """Creates a SecurityAnalyzer instance that will be used to analyze the agent actions

        Parameters:
        - security_analyzer: The name of the security analyzer to use
        """

        if security_analyzer:
            self.logger.debug(f'Using security analyzer: {security_analyzer}')
            self.security_analyzer = options.SecurityAnalyzers.get(
                security_analyzer, SecurityAnalyzer
            )(self.event_stream)

    def override_provider_tokens_with_custom_secret(
        self,
        git_provider_tokens: PROVIDER_TOKEN_TYPE | None,
        custom_secrets: CUSTOM_SECRETS_TYPE | None,
    ):
        if git_provider_tokens and custom_secrets:
            tokens = dict(git_provider_tokens)
            for provider, _ in tokens.items():
                token_name = ProviderHandler.get_provider_env_key(provider)
                if token_name in custom_secrets or token_name.upper() in custom_secrets:
                    del tokens[provider]

            return MappingProxyType(tokens)
        return git_provider_tokens

    async def _create_runtime(
        self,
        # runtime_name: str,
        # config: OpenHandsConfig,
        # agent: Agent,
        # git_provider_tokens: PROVIDER_TOKEN_TYPE | None = None,
        # custom_secrets: CUSTOM_SECRETS_TYPE | None = None,
        # selected_repository: str | None = None,
        # selected_branch: str | None = None,
        runtimeParams: RuntimeParams
    ) -> bool:
        """Creates a runtime instance

        Parameters:
        - runtime_name: The name of the runtime associated with the session
        - config:
        - agent:

        Return True on successfully connected, False if could not connect.
        Raises if already created, possibly in other situations.
        """

        if self.runtime is not None:
            raise RuntimeError('Runtime already created')

        custom_secrets_handler = UserSecrets(custom_secrets=custom_secrets or {})
        env_vars = custom_secrets_handler.get_env_vars()

        self.logger.debug(f'Initializing runtime `{runtime_name}` now...')
        runtime_cls = get_runtime_cls(runtime_name)
        if runtime_cls == RemoteRuntime:
            # If provider tokens is passed in custom secrets, then remove provider from provider tokens
            # We prioritize provider tokens set in custom secrets
            overrided_tokens = self.override_provider_tokens_with_custom_secret(
                git_provider_tokens, custom_secrets
            )

            self.runtime = runtime_cls(
                config=config,
                event_stream=self.event_stream,
                sid=self.sid,
                plugins=agent.sandbox_plugins,
                status_callback=self._status_callback,
                headless_mode=False,
                attach_to_existing=False,
                git_provider_tokens=overrided_tokens,
                env_vars=env_vars,
                user_id=self.user_id,
            )
        else:
            provider_handler = ProviderHandler(
                provider_tokens=git_provider_tokens
                or cast(PROVIDER_TOKEN_TYPE, MappingProxyType({}))
            )

            # Merge git provider tokens with custom secrets before passing over to runtime
            env_vars.update(await provider_handler.get_env_vars(expose_secrets=True))
            self.runtime = runtime_cls(
                config=config,
                event_stream=self.event_stream,
                sid=self.sid,
                plugins=agent.sandbox_plugins,
                status_callback=self._status_callback,
                headless_mode=False,
                attach_to_existing=False,
                env_vars=env_vars,
                git_provider_tokens=git_provider_tokens,
            )

        # FIXME: this sleep is a terrible hack.
        # This is to give the websocket a second to connect, so that
        # the status messages make it through to the frontend.
        # We should find a better way to plumb status messages through.
        await asyncio.sleep(1)
        try:
            await self.runtime.connect()
        except AgentRuntimeUnavailableError as e:
            self.logger.error(f'Runtime initialization failed: {e}')
            if self._status_callback:
                self._status_callback(
                    'error', 'STATUS$ERROR_RUNTIME_DISCONNECTED', str(e)
                )
            return False

        await self.runtime.clone_or_init_repo(
            git_provider_tokens, selected_repository, selected_branch
        )
        await call_sync_from_async(self.runtime.maybe_run_setup_script)
        await call_sync_from_async(self.runtime.maybe_setup_git_hooks)

        self.logger.debug(
            f'Runtime initialized with plugins: {[plugin.name for plugin in self.runtime.plugins]}'
        )
        return True

    def _create_controller(
        self,
        agent: Agent,
        confirmation_mode: bool,
        max_iterations: int,
        max_budget_per_task: float | None = None,
        agent_to_llm_config: dict[str, LLMConfig] | None = None,
        agent_configs: dict[str, AgentConfig] | None = None,
        replay_events: list[Event] | None = None,
    ) -> tuple[AgentController, bool]:
        """Creates an AgentController instance

        Parameters:
        - agent:
        - confirmation_mode: Whether to use confirmation mode
        - max_iterations:
        - max_budget_per_task:
        - agent_to_llm_config:
        - agent_configs:

        Returns:
            Agent Controller and a bool indicating if state was restored from a previous conversation
        """

        if self.controller is not None:
            raise RuntimeError('Controller already created')
        if self.runtime is None:
            raise RuntimeError(
                'Runtime must be initialized before the agent controller'
            )

        msg = (
            '\n--------------------------------- OpenHands Configuration ---------------------------------\n'
            f'LLM: {agent.llm.config.model}\n'
            f'Base URL: {agent.llm.config.base_url}\n'
            f'Agent: {agent.name}\n'
            f'Runtime: {self.runtime.__class__.__name__}\n'
            f'Plugins: {[p.name for p in agent.sandbox_plugins] if agent.sandbox_plugins else "None"}\n'
            '-------------------------------------------------------------------------------------------'
        )
        self.logger.debug(msg)
        initial_state = self._maybe_restore_state()
        controller = AgentController(
            sid=self.sid,
            user_id=self.user_id,
            file_store=self.file_store,
            event_stream=self.event_stream,
            agent=agent,
            iteration_delta=int(max_iterations),
            budget_per_task_delta=max_budget_per_task,
            agent_to_llm_config=agent_to_llm_config,
            agent_configs=agent_configs,
            confirmation_mode=confirmation_mode,
            headless_mode=False,
            status_callback=self._status_callback,
            initial_state=initial_state,
            replay_events=replay_events,
        )

        return (controller, initial_state is not None)

    async def _create_memory(
        self,
        selected_repository: str | None,
        repo_directory: str | None,
        conversation_instructions: str | None,
        custom_secrets_descriptions: dict[str, str],
    ) -> Memory:
        memory = Memory(
            event_stream=self.event_stream,
            sid=self.sid,
            status_callback=self._status_callback,
        )

        if self.runtime:
            # sets available hosts and other runtime info
            memory.set_runtime_info(self.runtime, custom_secrets_descriptions)
            memory.set_conversation_instructions(conversation_instructions)

            # loads microagents from repo/.openhands/microagents
            microagents: list[BaseMicroagent] = await call_sync_from_async(
                self.runtime.get_microagents_from_selected_repo,
                selected_repository or None,
            )
            memory.load_user_workspace_microagents(microagents)

            if selected_repository and repo_directory:
                memory.set_repository_info(selected_repository, repo_directory)
        return memory

    def _maybe_restore_state(self) -> State | None:
        """Helper method to handle state restore logic."""
        restored_state = None

        # Attempt to restore the state from session.
        # Use a heuristic to figure out if we should have a state:
        # if we have events in the stream.
        try:
            restored_state = State.restore_from_session(
                self.sid, self.file_store, self.user_id
            )
            self.logger.debug(f'Restored state from session, sid: {self.sid}')
        except Exception as e:
            if self.event_stream.get_latest_event_id() > 0:
                # if we have events, we should have a state
                self.logger.warning(f'State could not be restored: {e}')
            else:
                self.logger.debug('No events found, no state to restore')
        return restored_state

    def get_state(self) -> AgentState | None:
        controller = self.controller
        if controller:
            return controller.state.agent_state
        if time.time() > self._started_at + WAIT_TIME_BEFORE_CLOSE:
            # If 5 minutes have elapsed and we still don't have a controller, something has gone wrong
            return AgentState.ERROR
        return None

    def is_closed(self) -> bool:
        return self._closed
