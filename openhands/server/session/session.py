import asyncio
import time
from copy import deepcopy
from logging import LoggerAdapter

import socketio

from openhands.controller.agent import Agent
from openhands.core.config import OpenHandsConfig
from openhands.core.config.condenser_config import (
    BrowserOutputCondenserConfig,
    CondenserPipelineConfig,
    LLMSummarizingCondenserConfig,
)
from openhands.core.config.mcp_config import MCPConfig, OpenHandsMCPConfigImpl
from openhands.core.exceptions import MicroagentValidationError
from openhands.core.logger import OpenHandsLoggerAdapter
from openhands.core.schema import AgentState
from openhands.events.action import MessageAction, NullAction
from openhands.events.event import Event, EventSource
from openhands.events.observation import (
    AgentStateChangedObservation,
    CmdOutputObservation,
    NullObservation,
)
from openhands.integrations.provider import (
    CUSTOM_SECRETS_TYPE,
    PROVIDER_TOKEN_TYPE,
    ProviderHandler,
)

from openhands.events.observation.agent import RecallObservation
from openhands.events.observation.error import ErrorObservation
from openhands.events.serialization import event_from_dict, event_to_dict
from openhands.events.stream import EventStreamSubscriber
from openhands.llm.llm import LLM
from openhands.server.session.agent_session import AgentSession
from openhands.server.session.conversation_init_data import ConversationInitData
from openhands.storage.data_models.settings import Settings
from openhands.storage.files import FileStore
from openhands.server.session.schemas import (
    AgentSettings,
    LLMConfig,
    SandboxConfig,
    SecurityConfig,
    SessionParameters,
    CondenserPipelineConfig
)

from openhands.core.config.agent_config import AgentConfig

ROOM_KEY = 'room:{sid}'




def create_llm_config(base_llm_config, user_settings: Settings) -> LLMConfig:
    """사용자 설정과 기본 설정을 조합해 LLM 설정을 생성합니다."""
    return LLMConfig(
        model=user_settings.llm_model or base_llm_config.model,
        api_key=user_settings.llm_api_key,
        base_url=user_settings.llm_base_url,
    )

def create_security_config(base_security_config, user_settings: Settings) -> SecurityConfig:
    """보안 설정을 생성합니다."""
    return SecurityConfig(
        confirmation_mode=user_settings.confirmation_mode if user_settings.confirmation_mode is not None else base_security_config.confirmation_mode,
        security_analyzer=user_settings.security_analyzer or base_security_config.security_analyzer,
    )

def create_sandbox_config(base_sandbox_config, user_settings: Settings) -> SandboxConfig:
    # SandboxConfig 생성 로직
    return SandboxConfig(
        base_container_image=user_settings.sandbox_base_container_image or base_sandbox_config.base_container_image,
        runtime_container_image=user_settings.sandbox_runtime_container_image if user_settings.sandbox_base_container_image or user_settings.sandbox_runtime_container_image else base_sandbox_config.runtime_container_image,
    )

# def create_condenser_config(user_settings: Settings, llm_config: LLMConfig) -> CondenserPipelineConfig | None:
#     """Condenser 설정을 생성합니다. LLM 설정에 의존합니다."""
#     if user_settings.enable_default_condenser:
#         return CondenserPipelineConfig(
#             condensers=[
#                 BrowserOutputCondenserConfig(attention_window=2),
#                 LLMSummarizingCondenserConfig(
#                     llm_config={'model': llm_config.model, ...}, # dict로 변환
#                     ...
#                 ),
#             ]
#         )
#     return None

# def create_mcp_config(user_settings: Settings) -> MCPConfig:

#     # # MCPConfig 생성 로직
#     # mcp_config = self.user_settings.mcp_config or MCPConfig(sse_servers=[], stdio_servers=[])
#     # # Add OpenHands' MCP server by default
#     # openhands_mcp_server, openhands_mcp_stdio_servers = \
#     #     OpenHandsMCPConfigImpl.create_default_mcp_server_config(
#     #         self.base_config.mcp_host, self.base_config, self.user_id # Note: user_id is from user_settings here
#     #     )
#     # if openhands_mcp_server:
#     #     mcp_config.shttp_servers.append(openhands_mcp_server)
#     # mcp_config.stdio_servers.extend(openhands_mcp_stdio_servers)
#     # return mcp_config

#     # user_settings에 mcp_config가 있으면 그것을 사용하고, 없으면 기본 빈 객체를 생성합니다.
#     # OpenHands 기본 서버 추가 로직은 여기서 제거합니다.
#     return user_settings.mcp_config or MCPConfig(sse_servers=[], stdio_servers=[])


def create_condenser_config(user_settings, llm_config: LLMConfig) -> CondenserPipelineConfig | None:
    # CondenserPipelineConfig 생성 로직
    if user_settings.enable_default_condenser:
        return CondenserPipelineConfig(
            condensers=[
                BrowserOutputCondenserConfig(attention_window=2),
                LLMSummarizingCondenserConfig(
                    # llm_config={'model': llm_config.model, 'api_key': llm_config.api_key, 'base_url': llm_config.base_url}, # Pass as dict as expected by the config
                    llm_config={'model': llm_config.model, 'api_key': llm_config.api_key, 'base_url': llm_config.base_url}, # 수정된 부분
                    keep_first=4,
                    max_size=120,
                ),
            ]
        )
    return None

# 전체를 조립하는 메인 '파이프라인' 함수
def build_agent_settings(base_config, user_settings: Settings) -> AgentSettings:
    """
    설정 생성 함수들을 파이프라인처럼 연결하여
    최종 AgentSettings 객체를 만듭니다.
    """
    # 1. 각 부분을 독립적으로 생성
    llm_conf = create_llm_config(base_config.get_llm_config(), user_settings)
    security_conf = create_security_config(base_config.security, user_settings)
    sandbox_conf = create_sandbox_config(base_config.sandbox, user_settings)
    mcp_conf = user_settings.mcp_config or MCPConfig(sse_servers=[], stdio_servers=[]) # 컨텍스트 없는 기본 MCP 생성

    # 2. 다른 생성 결과에 의존하는 부분 생성
    condenser_conf = create_condenser_config(user_settings, llm_conf)

    # 3. 모든 조각을 모아 최종 데이터 구조 완성
    return AgentSettings(
        agent_cls=user_settings.agent or base_config.default_agent,
        max_iterations=user_settings.max_iterations or base_config.max_iterations,
        max_budget_per_task=user_settings.max_budget_per_task if user_settings.max_budget_per_task is not None else base_config.max_budget_per_task,
        llm_config=llm_conf,
        security_config=security_conf,
        sandbox_config=sandbox_conf,
        mcp_config=mcp_conf,
        condenser_config=condenser_conf,
    )

# 새 FP 함수 (Part 2: Data Transformation Logic)
def get_llm_config_from_agent(config: OpenHandsConfig, agent_name: str) -> LLMConfig:
    """주어진 config에서 agent_name에 맞는 LLMConfig를 반환합니다."""
    # 원본 self.config.get_llm_config_from_agent() 로직 재사용/적응
    # (실제 구현은 config의 내부 메서드를 호출하거나 로직 복사)
    return config.get_llm_config_from_agent(agent_name)  # config를 파라미터로 받아 self 제거

# 업데이트된 Composition 함수 (Part 3: Object Assembly Logic)
def compose_llm(config: OpenHandsConfig, agent_cls: str | None, llm_config: LLMConfig) -> LLM:
    agent_name = agent_cls if agent_cls is not None else 'agent'
    llm_specific_config = get_llm_config_from_agent(config, agent_name)  # 새 함수 호출
    return LLM(
        config=llm_specific_config,
        retry_listener=_notify_on_llm_retry,  # 별도 함수로 추출 (기존 self._notify_on_llm_retry 대신)
    )

def _notify_on_llm_retry(self, retries: int, max: int) -> None:
        msg_id = 'STATUS$LLM_RETRY'
        self.queue_status_message(
            'info', msg_id, f'Retrying LLM request, {retries} / {max}'
        )

# need to add AgentConfig
def compose_agent(agent_cls: type, llm:LLM, agent_config: AgentConfig):
    return Agent.get_cls(agent_cls)(llm, agent_config)



class Session:
    sid: str
    sio: socketio.AsyncServer | None
    last_active_ts: int = 0
    is_alive: bool = True
    loop: asyncio.AbstractEventLoop
    config: OpenHandsConfig
    file_store: FileStore
    user_id: str | None
    logger: LoggerAdapter

    def __init__(
        self,
        sid: str,
        config: OpenHandsConfig,
        file_store: FileStore,
        agent_session: AgentSession,
        sio: socketio.AsyncServer | None,
        user_id: str | None = None,
    ):
        self.sid = sid
        self.sio = sio
        self.last_active_ts = int(time.time())
        self.file_store = file_store
        self.logger = OpenHandsLoggerAdapter(extra={'session_id': sid})
        self.agent_session = agent_session
        self.config = deepcopy(config)
        self.loop = asyncio.get_event_loop()
        self.user_id = user_id

    async def close(self) -> None:
        if self.sio:
            await self.sio.emit(
                'oh_event',
                event_to_dict(
                    AgentStateChangedObservation('', AgentState.STOPPED.value)
                ),
                to=ROOM_KEY.format(sid=self.sid),
            )
        self.is_alive = False
        await self.agent_session.close()



    async def initialize_agent(
        self,
        settings: Settings,
        initial_message: MessageAction | None,
        replay_json: str | None,
    ) -> None:
        # self.agent_session.event_stream.add_event(
        #     AgentStateChangedObservation('', AgentState.LOADING),
        #     EventSource.ENVIRONMENT,
        # )
        # agent_cls = settings.agent or self.config.default_agent
        # self.config.security.confirmation_mode = (
        #     self.config.security.confirmation_mode
        #     if settings.confirmation_mode is None
        #     else settings.confirmation_mode
        # )
        # self.config.security.security_analyzer = (
        #     settings.security_analyzer or self.config.security.security_analyzer
        # )
        # self.config.sandbox.base_container_image = (
        #     settings.sandbox_base_container_image
        #     or self.config.sandbox.base_container_image
        # )
        # self.config.sandbox.runtime_container_image = (
        #     settings.sandbox_runtime_container_image
        #     if settings.sandbox_base_container_image
        #     or settings.sandbox_runtime_container_image
        #     else self.config.sandbox.runtime_container_image
        # )
        # max_iterations = settings.max_iterations or self.config.max_iterations

        # # Prioritize settings over config for max_budget_per_task
        # max_budget_per_task = (
        #     settings.max_budget_per_task
        #     if settings.max_budget_per_task is not None
        #     else self.config.max_budget_per_task
        # )

        # # This is a shallow copy of the default LLM config, so changes here will
        # # persist if we retrieve the default LLM config again when constructing
        # # the agent
        # default_llm_config = self.config.get_llm_config()
        # default_llm_config.model = settings.llm_model or ''
        # default_llm_config.api_key = settings.llm_api_key
        # default_llm_config.base_url = settings.llm_base_url
        # self.config.search_api_key = settings.search_api_key

        # # NOTE: this need to happen AFTER the config is updated with the search_api_key
        # self.config.mcp = settings.mcp_config or MCPConfig(
        #     sse_servers=[], stdio_servers=[]
        # )
        # # Add OpenHands' MCP server by default
        # openhands_mcp_server, openhands_mcp_stdio_servers = (
        #     OpenHandsMCPConfigImpl.create_default_mcp_server_config(
        #         self.config.mcp_host, self.config, self.user_id
        #     )
        # )
        # if openhands_mcp_server:
        #     self.config.mcp.shttp_servers.append(openhands_mcp_server)
        # self.config.mcp.stdio_servers.extend(openhands_mcp_stdio_servers)

        # # TODO: override other LLM config & agent config groups (#2075)

        # llm = self._create_llm(agent_cls)
        # agent_config = self.config.get_agent_config(agent_cls)

        # if settings.enable_default_condenser:
        #     # Default condenser chains a condenser that limits browser the total
        #     # size of browser observations with a condenser that limits the size
        #     # of the view given to the LLM. The order matters: with the browser
        #     # output first, the summarizer will only see the most recent browser
        #     # output, which should keep the summarization cost down.
        #     default_condenser_config = CondenserPipelineConfig(
        #         condensers=[
        #             BrowserOutputCondenserConfig(attention_window=2),
        #             LLMSummarizingCondenserConfig(
        #                 llm_config=llm.config, keep_first=4, max_size=120
        #             ),
        #         ]
        #     )

        #     self.logger.info(
        #         f'Enabling pipeline condenser with:'
        #         f' browser_output_masking(attention_window=2), '
        #         f' llm(model="{llm.config.model}", '
        #         f' base_url="{llm.config.base_url}", '
        #         f' keep_first=4, max_size=80)'
        #     )
        #     agent_config.condenser = default_condenser_config
        # agent = Agent.get_cls(agent_cls)(llm, agent_config)
        # print('----- print -----')
        # print(dir(agent))
        # print(agent.config)
        # print('-'*30)
        # exit(0)

        # git_provider_tokens = None
        # selected_repository = None
        # selected_branch = None
        # custom_secrets = None
        # conversation_instructions = None
        # if isinstance(settings, ConversationInitData):
        #     git_provider_tokens = settings.git_provider_tokens
        #     selected_repository = settings.selected_repository
        #     selected_branch = settings.selected_branch
        #     custom_secrets = settings.custom_secrets
        #     conversation_instructions = settings.conversation_instructions

        # try:
        #     await self.agent_session.start(
        #         runtime_name=self.config.runtime,
        #         config=self.config,
        #         agent=agent,
        #         max_iterations=max_iterations,
        #         max_budget_per_task=max_budget_per_task,
        #         agent_to_llm_config=self.config.get_agent_to_llm_config_map(),
        #         agent_configs=self.config.get_agent_configs(),
        #         git_provider_tokens=git_provider_tokens,
        #         custom_secrets=custom_secrets,
        #         selected_repository=selected_repository,
        #         selected_branch=selected_branch,
        #         initial_message=initial_message,
        #         conversation_instructions=conversation_instructions,
        #         replay_json=replay_json,
        #     )
        # except MicroagentValidationError as e:
        #     self.logger.exception(f'Error creating agent_session: {e}')
        #     # For microagent validation errors, provide more helpful information
        #     await self.send_error(f'Failed to create agent session: {str(e)}')
        #     return
        # except ValueError as e:
        #     self.logger.exception(f'Error creating agent_session: {e}')
        #     error_message = str(e)
        #     # For ValueError related to microagents, provide more helpful information
        #     if 'microagent' in error_message.lower():
        #         await self.send_error(
        #             f'Failed to create agent session: {error_message}'
        #         )
        #     else:
        #         # For other ValueErrors, just show the error class
        #         await self.send_error('Failed to create agent session: ValueError')
        #     return
        # except Exception as e:
        #     self.logger.exception(f'Error creating agent_session: {e}')
        #     # For other errors, just show the error class to avoid exposing sensitive information
        #     await self.send_error(
        #         f'Failed to create agent session: {e.__class__.__name__}'
        #     )
        #     return

        #WORKING
        try:
            self.agent_session.event_stream.add_event(
                AgentStateChangedObservation('', AgentState.LOADING),
                EventSource.ENVIRONMENT,
            )

            # 1. 순수 함수를 호출해 모든 설정을 한번에 생성 (데이터 변환)
            agent_settings = build_agent_settings(self.config, settings)

            # 2. OOP와 동일: 컨텍스트 데이터('user_id') 주입
            # 이 로직은 여전히 'Session'의 책임이므로 여기에 있는 것이 자연스럽습니다.
            openhands_mcp_server, stdio_servers = OpenHandsMCPConfigImpl.create_default_mcp_server_config(
                self.config.mcp_host, self.config, self.user_id
            )
            if openhands_mcp_server:
                agent_settings.mcp_config.shttp_servers.append(openhands_mcp_server)
            agent_settings.mcp_config.stdio_servers.extend(stdio_servers)

            # 3. 완성된 설정(데이터)을 바탕으로 실제 행위를 하는 '객체'들을 생성 (컴포지션)
            # 이 부분부터는 다시 OOP의 세계와 자연스럽게 연결됩니다.
            llm = compose_llm(self.config, agent_settings.agent_cls, agent_settings.llm_config)

            agent_config = self.config.get_agent_config(agent_settings.agent_cls)
            agent_config.condenser = agent_settings.condenser_config
            agent = compose_agent(agent_settings.agent_cls, llm, agent_config)

            # 3. 세션 시작에 필요한 파라미터를 담는 컨테이너 객체 생성
            session_params = self._prepare_session_parameters(settings, initial_message, replay_json)

            # 4. 단순화된 파라미터로 세션 시작
            await self.agent_session.start(
                config=self.config,
                agent=agent,
                settings=agent_settings,
                params=session_params
            )

        except (MicroagentValidationError, ValueError, Exception) as e:
            # 에러 처리 로직은 기존과 유사하게 유지
            self.logger.exception(f'Error creating agent_session: {e}')
            # ... 사용자에게 에러 메시지 전송 ...
            return

    # agent_session.start에 전달할 파라미터를 묶어주는 헬퍼 메서드나 데이터 클래스
    def _prepare_session_parameters(self, settings, initial_message, replay_json):
        if isinstance(settings, ConversationInitData):
            return SessionParameters(
                initial_message=initial_message,
                replay_json=replay_json,
                git_provider_tokens=settings.git_provider_tokens,
                # ... 등등
            )
        return SessionParameters(initial_message=initial_message, replay_json=replay_json)

    def _create_llm(self, agent_cls: str | None, llm_config: LLMConfig) -> LLM:
        """Initialize LLM, extracted for testing."""
        agent_name = agent_cls if agent_cls is not None else 'agent'
        return LLM(
            config=self.config.get_llm_config_from_agent(agent_name),
            retry_listener=self._notify_on_llm_retry,
        )

    def _notify_on_llm_retry(self, retries: int, max: int) -> None:
        msg_id = 'STATUS$LLM_RETRY'
        self.queue_status_message(
            'info', msg_id, f'Retrying LLM request, {retries} / {max}'
        )

    def on_event(self, event: Event) -> None:
        asyncio.get_event_loop().run_until_complete(self._on_event(event))

    async def _on_event(self, event: Event) -> None:
        """Callback function for events that mainly come from the agent.
        Event is the base class for any agent action and observation.

        Args:
            event: The agent event (Observation or Action).
        """
        if isinstance(event, NullAction):
            return
        if isinstance(event, NullObservation):
            return
        if event.source == EventSource.AGENT:
            await self.send(event_to_dict(event))
        elif event.source == EventSource.USER:
            await self.send(event_to_dict(event))
        # NOTE: ipython observations are not sent here currently
        elif event.source == EventSource.ENVIRONMENT and isinstance(
            event,
            (CmdOutputObservation, AgentStateChangedObservation, RecallObservation),
        ):
            print('---environments----')
            print(event)
            print(event_to_dict(event))
            print('-'*50)
            # feedback from the environment to agent actions is understood as agent events by the UI
            event_dict = event_to_dict(event)
            event_dict['source'] = EventSource.AGENT
            await self.send(event_dict)
            if (
                isinstance(event, AgentStateChangedObservation)
                and event.agent_state == AgentState.ERROR
            ):
                self.logger.error(
                    f'Agent status error: {event.reason}',
                    extra={'signal': 'agent_status_error'},
                )
        elif isinstance(event, ErrorObservation):
            # send error events as agent events to the UI
            event_dict = event_to_dict(event)
            event_dict['source'] = EventSource.AGENT
            await self.send(event_dict)

    async def dispatch(self, data: dict) -> None:
        event = event_from_dict(data.copy())
        # This checks if the model supports images
        if isinstance(event, MessageAction) and event.image_urls:
            controller = self.agent_session.controller
            if controller:
                if controller.agent.llm.config.disable_vision:
                    await self.send_error(
                        'Support for images is disabled for this model, try without an image.'
                    )
                    return
                if not controller.agent.llm.vision_is_active():
                    await self.send_error(
                        'Model does not support image upload, change to a different model or try without an image.'
                    )
                    return
        self.agent_session.event_stream.add_event(event, EventSource.USER)

    async def send(self, data: dict[str, object]) -> None:
        if asyncio.get_running_loop() != self.loop:
            self.loop.create_task(self._send(data))
            return
        await self._send(data)

    async def _send(self, data: dict[str, object]) -> bool:
        try:
            if not self.is_alive:
                return False
            if self.sio:
                await self.sio.emit('oh_event', data, to=ROOM_KEY.format(sid=self.sid))
            await asyncio.sleep(0.001)  # This flushes the data to the client
            self.last_active_ts = int(time.time())
            return True
        except RuntimeError as e:
            self.logger.error(f'Error sending data to websocket: {str(e)}')
            self.is_alive = False
            return False

    async def send_error(self, message: str) -> None:
        """Sends an error message to the client."""
        await self.send({'error': True, 'message': message})

    async def _send_status_message(self, msg_type: str, id: str, message: str) -> None:
        """Sends a status message to the client."""
        if msg_type == 'error':
            agent_session = self.agent_session
            controller = self.agent_session.controller
            if controller is not None and not agent_session.is_closed():
                await controller.set_agent_state_to(AgentState.ERROR)
            self.logger.error(
                f'Agent status error: {message}',
                extra={'signal': 'agent_status_error'},
            )
        await self.send(
            {'status_update': True, 'type': msg_type, 'id': id, 'message': message}
        )

    def queue_status_message(self, msg_type: str, id: str, message: str) -> None:
        """Queues a status message to be sent asynchronously."""
        asyncio.run_coroutine_threadsafe(
            self._send_status_message(msg_type, id, message), self.loop
        )
