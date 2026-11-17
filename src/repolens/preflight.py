"""Offline configuration inventory; never starts or connects to RepoLens services."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit
from repolens import __version__

FEATURES = ('model', 'postgres', 'redis', 'hybrid', 'rerank', 'documents', 'renderer')
DEPENDENCIES = ('fastapi', 'pydantic', 'jinja2', 'httpx', 'httpcore', 'uvicorn', 'certifi',
                'langgraph', 'langsmith', 'langgraph-checkpoint-sqlite',
                'langgraph-checkpoint-postgres', 'psycopg', 'redis', 'mcp')


def requirements(features, tools_only=False):
    selected = set(features)
    if not selected <= set(FEATURES):
        raise ValueError('invalid_preflight_requirements')
    if not tools_only:
        selected.add('model')
    if 'rerank' in selected:
        selected.add('hybrid')
    if 'renderer' in selected:
        selected.add('documents')
    return selected


def provider_url(value):
    try:
        parsed = urlsplit(value)
        return bool(parsed.scheme in {'http', 'https'} and parsed.hostname and
                    not parsed.hostname.endswith('.example') and not parsed.username and
                    not parsed.password and not parsed.query and not parsed.fragment and
                    (parsed.port is None or parsed.port > 0))
    except ValueError:
        return False


def present(value):
    return bool(value.strip()) and value.strip() not in {'replace-locally-never-commit', 'your-tool-calling-model'}


def report(required, checks, **metadata):
    return dict(version=__version__, configuration_ready=not any(item['status'] == 'error' for item in checks),
                runtime_verified=False, network_probes_performed=False, required_features=sorted(required),
                checks=checks, **metadata)


def inspect_configuration(settings, required):
    """Return only fixed diagnostics and versions, never configuration values or errors."""
    checks = []

    def add(code, status, message):
        checks.append(dict(code=code, status=status, message=message))

    def feature(name, valid, supplied, success, action, active=False):
        status = 'ok' if valid else 'error' if name in required or active else 'warning' if supplied else 'skipped'
        add(name + ('_configured' if valid else '_not_ready'), status, success if valid else action)

    versions = {}
    add('python_version', 'ok' if sys.version_info >= (3, 12) else 'error', '需要 Python 3.12 或更新版本。')
    for name in DEPENDENCIES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            add('dependency_' + name.replace('-', '_'), 'error', '缺少项目锁定依赖；按部署文档安装依赖。')
    add('dependency_scope', 'info', '只核对发行包存在，未验证导入、二进制兼容或服务运行。')

    root, data = settings.workspace_root, settings.data_dir
    add('workspace_directory', 'ok' if root.is_dir() and os.access(root, os.R_OK | os.X_OK) else 'error',
        '工作目录必须存在且当前进程可读取。')
    parent = data
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    usable = parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
    add('data_directory', 'ok' if usable else 'error', '仅检查数据目录或最近现有父目录的权限提示；未创建目录或试写文件。')

    model_ok = present(settings.model_name) and present(settings.model_key.get_secret_value()) and provider_url(settings.model_url)
    feature('model', model_ok, bool(settings.model_name or settings.model_key.get_secret_value()),
            '模型配置项齐备；凭据、连通性及工具调用能力尚未验证。',
            '在当前进程配置有效的 REPOLENS_MODEL、REPOLENS_API_KEY 和 REPOLENS_MODEL_URL，替换示例值。')

    database = settings.database_url.get_secret_value()
    if database:
        try:
            from psycopg.conninfo import conninfo_to_dict
            conninfo_to_dict(database)  # libpq syntax parser only; no connection.
            valid_database = True
        except Exception:
            valid_database = False  # Exception strings can contain passwords/DSNs.
    else:
        valid_database = False
        add('sqlite_selected', 'ok', '未指定 PostgreSQL，当前选择 SQLite；未打开或创建数据库。')
    feature('postgres', valid_database, bool(database), 'PostgreSQL DSN 语法可解析；认证、数据库和共享目录尚未验证。',
            '在当前进程配置有效的 REPOLENS_DATABASE_URL；密码可沿用 libpq 本地凭据方式。', active=bool(database))

    redis_url = settings.redis_url.get_secret_value()
    valid_redis = False
    if redis_url:
        try:
            from redis.connection import parse_url
            parsed = parse_url(redis_url)  # Parse only; no client/pool/socket.
            valid_redis = bool(parsed.get('path')) if redis_url.startswith('unix://') else True
        except Exception:
            pass
    redis_used = settings.execution_mode != 'embedded'
    feature('redis', valid_redis and redis_used, bool(redis_url), 'Redis 唤醒配置语法可解析；服务连通性尚未验证。',
            'Redis 唤醒需要 api/worker 拆分模式及有效 REPOLENS_REDIS_URL；未配置时拆分模式可用数据库轮询。',
            active=bool(redis_url) and redis_used)

    hybrid_values = (settings.milvus_url, settings.embedding_url, settings.embedding_model)
    feature('hybrid', all(hybrid_values), any(hybrid_values), '混合检索配置项齐备；服务、维度、凭据和索引尚未验证。',
            '配置 REPOLENS_MILVUS_URL、REPOLENS_EMBEDDING_URL、REPOLENS_EMBEDDING_MODEL。')
    rerank_values = (settings.rerank_url, settings.rerank_model)
    feature('rerank', all(rerank_values) and all(hybrid_values), any(rerank_values),
            '重排及混合检索配置项齐备；实际重排尚未验证。', '重排需要完整混合检索配置及 REPOLENS_RERANK_URL、REPOLENS_RERANK_MODEL。')
    feature('documents', bool(settings.document_hosts), bool(settings.document_hosts),
            '网页允许站点已配置；网络策略和正文采集尚未验证。', '按需配置 REPOLENS_DOCUMENT_HOSTS；默认不开放网页采集。')
    renderer_ok = sys.platform.startswith('linux') and settings.renderer_socket is not None and bool(settings.document_hosts)
    feature('renderer', renderer_ok, settings.renderer_socket is not None,
            'Linux 渲染 socket 路径及网页允许站点已配置；未连接 socket 或验证浏览器隔离。',
            '动态渲染需 Linux 隔离 sidecar、REPOLENS_RENDERER_SOCKET 和网页允许站点；Windows 原生不运行渲染器。')
    add('dotenv_not_loaded', 'info', 'Python 不自动读取 .env；本报告仅描述当前进程环境，不能代替 Compose 容器配置检查。')
    add('docker_cli', 'info' if shutil.which('docker') else 'skipped', '仅记录 Docker CLI 是否可定位；未查询 Docker 引擎或启动容器。')
    return report(required, checks, execution_mode=settings.execution_mode, installed_versions=versions,
                  dotenv_file_present=Path('.env').is_file(), docker_cli_found=bool(shutil.which('docker')))


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Do not echo arbitrary invalid arguments, which might accidentally contain secrets.
        self.exit(2, 'invalid_preflight_arguments: use --help\n')


def main():
    parser = Parser(description=__doc__)
    parser.add_argument('--require', choices=FEATURES, action='append', default=[], help='Repeat to require optional features')
    parser.add_argument('--tools-only', action='store_true', help='Do not require a configured investigation model')
    parser.add_argument('--json', action='store_true', help='Print a redacted machine-readable report')
    args = parser.parse_args()
    required = requirements(args.require, args.tools_only)
    try:
        from repolens.config import Settings
        value = inspect_configuration(Settings.from_env(), required)
    except (ValueError, OSError, ImportError):
        value = report(required, [dict(code='invalid_environment_configuration', status='error',
                                      message='环境配置、路径或配置依赖无法解析；请按 .env.example 核对，原始值和异常已隐藏。')])
    if args.json:
        # ASCII JSON survives native Windows redirection regardless of code page.
        print(json.dumps(value, ensure_ascii=True, indent=2))
    else:
        print('配置检查：' + ('齐备' if value['configuration_ready'] else '有阻塞项') + '；运行时尚未验收。')
        for item in value['checks']:
            print(f"[{item['status']}] {item['code']}: {item['message']}")
    return 0 if value['configuration_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
