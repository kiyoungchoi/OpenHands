from dataclasses import dataclass, field
from typing import List, Dict

from openhands.core.config.condenser_config import CondenserPipelineConfig
from openhands.core.config.mcp_config import MCPConfig
from openhands.integrations.provider import CUSTOM_SECRETS_TYPE

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

@dataclass
class SessionParameters:
    """
    세션 시작에 필요한 파라미터를 담는 데이터 클래스입니다.
    필요한 필드를 상황에 맞게 추가/수정하세요.
    """
    initial_message: str | None = None
    replay_json: str | None = None
    git_provider_tokens: object = None  # 타입을 구체적으로 지정할 수 있으면 수정하세요
    custom_secrets: CUSTOM_SECRETS_TYPE | None = None
    conversation_instructions: str | None = None
    selected_repository: str | None = None
    selected_branch: str | None = None
    # 기타 필요한 파라미터들...
