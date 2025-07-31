# 해당 레포의 복잡도를 이해하고자 만들게 되었음 (나도 탐색중이라, 따로 기준없이 시작하게됨.)

# 이 ramp 파일의 목적은 처음 접근하는 사람들에게 쉽게 이해를 돕고자 작성된 파일입니다.
# 이 파일은 누구나 언제든 작동 가능하고, 수정가능합니다.


#*******
print("******* CONFIG PART *******")

# start with config
# In app.py, load basic config
from openhands.server.shared import conversation_manager
# print(conversation_manager)
"""
StandaloneConversationManager(sio=<socketio.async_server.AsyncServer object at 0x7efdf21bdaf0>, config=OpenHandsConfig(llms={'llm': LLMConfig(model='claude-sonnet-4-20250514', api_key=None, base_url=None, api_version=None, aws_access_key_id=None, aws_secret_access_key=None, aws_region_name=None, openrouter_site_url='https://docs.all-hands.dev/', openrouter_app_name='OpenHands', num_retries=4, retry_multiplier=2, retry_min_wait=5, retry_max_wait=30, timeout=None, max_message_chars=30000, temperature=0.0, top_p=1.0, top_k=None, custom_llm_provider=None, max_input_tokens=None, max_output_tokens=None, input_cost_per_token=None, output_cost_per_token=None, ollama_base_url=None, drop_params=True, modify_params=True, disable_vision=None, caching_prompt=True, log_completions=False, log_completions_folder='/app/logs/completions', custom_tokenizer=None, native_tool_calling=None, reasoning_effort='high', seed=None)}, agents={'agent': AgentConfig(llm_config=None, classpath=None, system_prompt_filename='system_prompt.j2', enable_browsing=True, enable_llm_editor=False, enable_editor=True, enable_jupyter=True, enable_cmd=True, enable_think=True, enable_finish=True, enable_prompt_extensions=True, enable_mcp=True, disabled_microagents=[], enable_history_truncation=True, enable_som_visual_browsing=True, condenser=NoOpCondenserConfig(type='noop'), extended=ExtendedConfig())}, default_agent='CodeActAgent', sandbox=SandboxConfig(remote_runtime_api_url='http://localhost:8000', local_runtime_url='http://localhost', keep_runtime_alive=False, pause_closed_runtimes=True, rm_all_containers=False, api_key=None, base_container_image='nikolaik/python-nodejs:python3.12-nodejs22', runtime_container_image='ghcr.io/all-hands-ai/runtime:0.45-nikolaik', user_id=501, timeout=120, remote_runtime_init_timeout=180, remote_runtime_api_timeout=10, remote_runtime_enable_retries=True, remote_runtime_class=None, enable_auto_lint=False, use_host_network=False, runtime_binding_address='0.0.0.0', runtime_extra_build_args=None, initialize_plugins=True, force_rebuild_runtime=False, runtime_extra_deps=None, runtime_startup_env_vars={}, browsergym_eval_env=None, platform=None, close_delay=3600, remote_runtime_resource_factor=1, enable_gpu=False, docker_runtime_kwargs=None, selected_repo=None, trusted_dirs=[], vscode_port=None, volumes=None, runtime_mount=None), security=SecurityConfig(confirmation_mode=False, security_analyzer=None), extended=ExtendedConfig(), runtime='docker', file_store='local', file_store_path='~/.openhands', file_store_web_hook_url=None, file_store_web_hook_headers=None, save_trajectory_path=None, save_screenshots_in_trajectory=False, replay_trajectory_path=None, search_api_key=None, workspace_base=None, workspace_mount_path='/Users/mac01/Desktop/personal/OpenHands/workspace', workspace_mount_path_in_sandbox='/workspace', workspace_mount_rewrite=None, cache_dir='/tmp/cache', run_as_openhands=True, max_iterations=500, max_budget_per_task=None, e2b_api_key=None, modal_api_token_id=None, modal_api_token_secret=None, disable_color=False, jwt_secret=SecretStr('**********'), debug=False, file_uploads_max_file_size_mb=0, file_uploads_restrict_file_types=False, file_uploads_allowed_extensions=['.*'], runloop_api_key=None, daytona_api_key=None, daytona_api_url='https://app.daytona.io/api', daytona_target='eu', cli_multiline_input=False, conversation_max_age_seconds=864000, enable_default_condenser=True, max_concurrent_conversations=3, mcp_host='localhost:3000', mcp=MCPConfig(sse_servers=[], stdio_servers=[], shttp_servers=[]), kubernetes=KubernetesConfig(namespace='default', ingress_domain='localhost', pvc_storage_size='2Gi', pvc_storage_class=None, resource_cpu_request='1', resource_memory_request='1Gi', resource_memory_limit='2Gi', image_pull_secret=None, ingress_tls_secret=None, node_selector_key=None, node_selector_val=None, tolerations_yaml=None, privileged=False)), file_store=<openhands.storage.local.LocalFileStore object at 0x7efdf21bd850>, server_config=<openhands.server.config.server_config.ServerConfig object at 0x7efdf21bd820>, monitoring_listener=<openhands.server.monitoring.MonitoringListener object at 0x7efdf249cdd0>, _local_agent_loops_by_sid={}, _local_connection_id_to_session_id={}, _active_conversations={}, _detached_conversations={}, _conversations_lock=<asyncio.locks.Lock object at 0x7efdf21bd8b0 [unlocked]>, _cleanup_task=None, _conversation_store_class=None)
"""
assert conversation_manager.config.sandbox.runtime_mount == None

# what if I add env in config.toml
import os
from openhands.core.config.openhands_config import OpenHandsConfig
from openhands.core.config import load_openhands_config

config_file_path = "test_config.toml"
config_content_to_add = """
[sandbox]
# Runtime container image to use (if not provided, will be built from base_container_image)
runtime_mount = '/workspace:/workspace:rw'
"""
try:
    with open(config_file_path, "w") as f: # "w" 모드는 파일을 덮어씁니다. "a"는 파일 끝에 추가합니다.
        f.write(config_content_to_add)

    config: OpenHandsConfig = load_openhands_config(config_file=config_file_path)
    assert config.sandbox.runtime_mount == "/workspace:/workspace:rw"
finally:
    os.remove(config_file_path)

# should care about "speed" later


print("******* New Conversation PART *******")

from openhands.core.config import load_openhands_config
from openhands.server.types import ServerConfigInterface
from openhands.server.config.server_config import ServerConfig, load_server_config
from openhands.server.conversation_manager.conversation_manager import (
    ConversationManager,
)
from openhands.utils.import_utils import get_impl

server_config_interface: ServerConfigInterface = load_server_config()
assert isinstance(server_config_interface, ServerConfig), (
    'Loaded server config interface is not a ServerConfig, despite this being assumed'
)
server_config: ServerConfig = server_config_interface
ConversationManagerImpl = get_impl(
    ConversationManager,
    server_config.conversation_manager_class,
)

# print(ConversationManagerImpl)
"""
<class 'openhands.server.conversation_manager.standalone_conversation_manager.StandaloneConversationManager'>
"""

from openhands.server.conversation_manager.standalone_conversation_manager import StandaloneConversationManager
assert ConversationManagerImpl is StandaloneConversationManager, 'ConversationManagerImpl은 StandaloneConversationManager여야 합니다.'

ConversationManager_DEFAULT = get_impl(ConversationManager, None)
assert ConversationManager_DEFAULT is ConversationManager, 'ConversationManager_DEFAULT ConversationManager 합니다.'

print("******* First time to start new conversation PART *******")

import asyncio
import pprint
from openhands.storage.data_models.settings import Settings
from openhands.server.shared import (
    ConversationStoreImpl,
    SecretsStoreImpl,
    SettingsStoreImpl,
    config,
    conversation_manager,
    server_config,
)
from openhands.server.routes.manage_conversations import (
    ConversationResponse,
    InitSessionRequest,
    delete_conversation,
    get_conversation,
    new_conversation,
    search_conversations,
)
from unittest.mock import AsyncMock, MagicMock, patch
from types import MappingProxyType
from openhands.server.user_auth.user_auth import AuthType
from openhands.integrations.provider import ProviderType, ProviderToken # ProviderType과 ProviderToken을 임포트합니다.
from pydantic import SecretStr # SecretStr을 임포트합니다.
from openhands.storage.settings.file_settings_store import FileSettingsStore
from openhands.cli.main import run_setup_flow


async def main():
    # # settings from cli
    # config = load_openhands_config()
    # settings_store = await FileSettingsStore.get_instance(config=config, user_id=None)
    # settings = await settings_store.load()

    # settings from web process
    settings_store = await SettingsStoreImpl.get_instance(config, user_id=None)
    settings = await settings_store.load()

    # add for easy setup in terminal
    if not settings:
        # Clear the terminal before showing the banner
        await run_setup_flow(config, settings_store)
        banner_shown = True
        settings = await settings_store.load()

    test_user_id = "test_user_id"
    conversation_store = await ConversationStoreImpl.get_instance(config, test_user_id)

    test_request = InitSessionRequest(
        # repository='test/repo',
        repository='',
        selected_branch='main',
        initial_user_msg='Hello, agent!',
        image_urls=['https://example.com/image.jpg'],
    )

    mock_user_secrets = MagicMock()
    mock_user_secrets.custom_secrets = MappingProxyType({})

    response = await new_conversation(
        data=test_request,
        user_id='test_user',
        provider_tokens=MappingProxyType({ProviderType.GITHUB: ProviderToken(token=SecretStr('token123'))}), # 키와 값을 올바른 타입으로 변경합니다.
        user_secrets=mock_user_secrets,        auth_type=None,
    )
    """
    ConversationResponse(status='ok', conversation_id='80f9e6f38bc544bd900d98a09821c5bf', message=None, conversation_status=<ConversationStatus.STARTING: 'STARTING'>)
    """

    print("******* Agent session start PART *******")

    conversation_id = response.conversation_id
    # print(f"**새 대화 시작: {conversation_id}, 상태: {response.conversation_status}")
    # DEBUG = os.getenv('DEBUG', 'True').lower() in ['true', '1', 'yes'] # openhands/core/logger.py

    ## cli -> self-docker: not enough
    ## web -> host local docker independently

    #  conversation_manager.maybe_start_agent_loop() -> session.initialize_agent -> self.agent_session.start

    # self.agent_session.start -> self.runtime.connect() ->  self.init_container()

    # NOTE: 런타임이 완전히 초기화될 시간을 주기 위해 추가
    #       이 파일을 테스트용으로 실행할 경우, 이 sleep 시간을 충분히 길게 설정해야 합니다.
    #       실제 프로덕션 코드에서는 이와 같은 무작정 대기는 적절하지 않습니다.
    # await asyncio.sleep(60) # 60초 동안 대기하여 런타임 초기화 시간 확보

    # 에이전트 세션이 완료될 때까지 대기
    while True:
        status_response = await get_conversation(conversation_id=conversation_id, conversation_store=conversation_store)
        print(status_response)
        current_status = status_response.status
        print(f"현재 대화 상태: {current_status}")

        if current_status.value in ['COMPLETED', 'STOPPED', 'ERROR']:
            print(f"대화가 최종 상태 '{current_status.value}'에 도달했습니다.")
            break
        else:
            print(current_status.value == "STARTING")
        await asyncio.sleep(5) # 5초마다 상태를 확인합니다


asyncio.run(main())


# rewrite openhands below
