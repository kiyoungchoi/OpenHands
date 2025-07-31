# from unittest.mock import ANY, AsyncMock, patch

# import pytest
# from litellm.exceptions import (
#     RateLimitError,
# )

# from openhands.core.config.llm_config import LLMConfig
# from openhands.core.config.openhands_config import OpenHandsConfig
# from openhands.server.session.session import Session
# from openhands.storage.memory import InMemoryFileStore


# @pytest.fixture
# def mock_status_callback():
#     return AsyncMock()


# @pytest.fixture
# def mock_sio():
#     return AsyncMock()


# @pytest.fixture
# def default_llm_config():
#     return LLMConfig(
#         model='gpt-4o',
#         api_key='test_key',
#         num_retries=2,
#         retry_min_wait=1,
#         retry_max_wait=2,
#     )


# @pytest.mark.asyncio
# @patch('openhands.llm.llm.litellm_completion')
# async def test_notify_on_llm_retry(
#     mock_litellm_completion, mock_sio, default_llm_config
# ):
#     config = OpenHandsConfig()
#     config.set_llm_config(default_llm_config)
#     session = Session(
#         sid='..sid..',
#         file_store=InMemoryFileStore({}),
#         config=config,
#         sio=mock_sio,
#         user_id='..uid..',
#     )
#     session.queue_status_message = AsyncMock()

#     with patch('time.sleep') as _mock_sleep:
#         mock_litellm_completion.side_effect = [
#             RateLimitError(
#                 'Rate limit exceeded', llm_provider='test_provider', model='test_model'
#             ),
#             {'choices': [{'message': {'content': 'Retry successful'}}]},
#         ]
#     llm = session._create_llm('..cls..')

#     llm.completion(
#         messages=[{'role': 'user', 'content': 'Hello!'}],
#         stream=False,
#     )

#     assert mock_litellm_completion.call_count == 2
#     session.queue_status_message.assert_called_once_with(
#         'info', 'STATUS$LLM_RETRY', ANY
#     )
#     await session.close()

import pytest
from unittest.mock import MagicMock, patch
from openhands.llm.llm import LLM
from openhands.core.config import OpenHandsConfig, LLMConfig
from openhands.server.session.session import get_llm_config_from_agent, compose_llm, compose_agent, AgentConfig

# 단계 3: Data Transformation 함수 테스트 (get_llm_config_from_agent)
def test_get_llm_config_from_agent():
    # Mock config 객체 (FP라 mock 간단)
    mock_config = MagicMock(spec=OpenHandsConfig)
    mock_config.get_llm_config_from_agent.return_value = LLMConfig(model='gpt-4')

    result = get_llm_config_from_agent(mock_config, 'test_agent')

    print(f"\n[실험] result의 타입: {type(result)}")
    print(f"[실험] result의 내용: {result}")
    assert result.model == 'gpt-4'  # 간단: mock 없이 파라미터만
    mock_config.get_llm_config_from_agent.assert_called_once_with('test_agent')

# 단계 4: Composition 함수 테스트 (compose_llm)
def test_compose_llm():
    mock_config = MagicMock(spec=OpenHandsConfig)
    mock_config.get_llm_config_from_agent.return_value = LLMConfig(model='gpt-4')

    # notify_on_llm_retry도 mock (별도 함수라 쉽게)
    def mock_notify(retries, max_retries):
        pass

    llm = compose_llm(mock_config, 'test_agent', LLMConfig())
    assert isinstance(llm, LLM)
    assert llm.config.model == 'gpt-4'  # FP라 직접 호출, mock setup 최소화

# 단계 4: Composition 함수 테스트 (compose_agent)
def test_compose_agent():
    mock_llm = MagicMock(spec=LLM)
    mock_agent_config = MagicMock(spec=AgentConfig)

    # Agent.get_cls를 mock (실제로는 import 해서 사용)
    mock_agent_class = MagicMock()
    mock_agent_class.return_value = 'MockAgentInstance'
    with patch(
        'openhands.controller.agent.Agent.get_cls', return_value=mock_agent_class
    ):
        agent = compose_agent('TestAgentCls', mock_llm, mock_agent_config)
        assert agent == 'MockAgentInstance'  # 생성 검증, FP라 독립적 테스트 가능

# 추가: 에지 케이스 (agent_cls None)
def test_compose_llm_with_none_agent_cls():
    mock_config = MagicMock()
    mock_config.get_llm_config_from_agent.return_value = LLMConfig(model='default')
    llm = compose_llm(mock_config, None, LLMConfig())
    assert llm.config.model == 'default'  # FP라 에지 케이스 쉽게 커버
