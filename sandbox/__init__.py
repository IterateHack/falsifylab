from .base import ExecResult, Executor
from .local import LocalExecutor

__all__ = ["ExecResult", "Executor", "LocalExecutor", "get_executor"]


def get_executor(backend: str = "local", **kwargs):
    """Factory so the backend is a config switch, not a code change."""
    if backend == "local":
        return LocalExecutor(**kwargs)
    if backend == "modal":
        from .modal_exec import ModalExecutor  # imported lazily: modal is optional
        return ModalExecutor(**kwargs)
    raise ValueError(f"unknown sandbox backend {backend!r}")
