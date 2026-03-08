import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def install_salt_stub():
    salt_module = types.ModuleType('salt')
    exceptions_module = types.ModuleType('salt.exceptions')

    class CommandExecutionError(Exception):
        pass

    class SaltException(Exception):
        pass

    exceptions_module.CommandExecutionError = CommandExecutionError
    exceptions_module.SaltException = SaltException
    salt_module.exceptions = exceptions_module
    sys.modules['salt'] = salt_module
    sys.modules['salt.exceptions'] = exceptions_module
    return exceptions_module


def load_repo_module(module_name, relative_path):
    install_salt_stub()
    module_path = REPO_ROOT / relative_path
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module