"""웹에서 값을 찾는 공통 모듈.

찾을 대상은 config 의 targets 로 정의하며, 코드는 특정 값 이름을 알지 못한다.
"""
from extractors.config import (
    Config,
    ConfigError,
    Target,
    available_envs,
    load_config,
    load_env_file,
)
from extractors.finder import NotFoundError, ValueFinder, find_in_json, normalize
from extractors.login import LoginFailed, login

__all__ = [
    "Config",
    "ConfigError",
    "Target",
    "available_envs",
    "load_config",
    "load_env_file",
    "NotFoundError",
    "ValueFinder",
    "find_in_json",
    "normalize",
    "LoginFailed",
    "login",
]
