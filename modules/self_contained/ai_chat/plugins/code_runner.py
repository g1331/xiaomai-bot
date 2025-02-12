import ast
import asyncio
import math
import sys
from io import StringIO
from typing import Dict, Any, Set, List, FrozenSet
from pydantic import validator

from RestrictedPython import compile_restricted
from RestrictedPython.Eval import default_guarded_getitem
from RestrictedPython.Guards import safe_builtins, guarded_iter_unpack_sequence, guarded_unpack_sequence, safer_getattr
from RestrictedPython.Utilities import utility_builtins

from ..core.plugin import BasePlugin, PluginConfig, PluginDescription

# 尝试导入resource模块，Windows平台通常不支持
try:
    import resource

    RESOURCE_AVAILABLE = True
except ImportError:
    RESOURCE_AVAILABLE = False


class CodeRunnerConfig(PluginConfig):
    """代码执行插件配置。"""
    timeout: int = 5  # 执行超时时间(秒)
    max_code_length: int = 1000  # 最大代码长度
    allowed_modules: FrozenSet[str] = frozenset({
        "math", "random", "statistics", "decimal"
    })
    allowed_builtins: FrozenSet[str] = frozenset({
        'abs', 'min', 'max', 'sum', 'len'
    })

    @property
    def required_fields(self) -> Set[str]:
        return set()

    def dict(self, *args, **kwargs):
        """重写dict方法，确保Set被序列化为list"""
        d = super().dict(*args, **kwargs)
        # 将Set转换为list以便JSON序列化
        d['allowed_modules'] = list(self.allowed_modules)
        d['allowed_builtins'] = list(self.allowed_builtins)
        return d

    @validator('allowed_modules', 'allowed_builtins', pre=True)
    def ensure_set(cls, v):
        """确保值总是被转换为Set"""
        if isinstance(v, list):
            return set(v)
        if isinstance(v, set):
            return v
        raise ValueError('Must be a list or set')


class CodeRunner(BasePlugin):
    """Python代码执行插件实现类。"""

    def __init__(self, config: CodeRunnerConfig):
        super().__init__(config)
        # 基于RestrictedPython配置安全环境
        self.safe_globals = {
            "__builtins__": safe_builtins,
            "_getattr_": safer_getattr,
            "_getitem_": default_guarded_getitem,
            "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
            "_unpack_sequence_": guarded_unpack_sequence,
            "math": math,
            **utility_builtins
        }

    @property
    def description(self) -> PluginDescription:
        return PluginDescription(
            name="code_runner",
            description="安全执行Python代码，用于计算数学表达式或者简单的代码执行，不能执行有害的代码。",
            parameters={
                "code": "要执行的Python代码",
                "timeout": f"可选，执行超时时间(秒)，默认{self.config.timeout}秒"
            },
            example=(
                "计算数学表达式：\n"
                "{'code': 'import math\\n"
                "result = math.sqrt(16) + math.pi\\n"
                "print(f\"结果: {result}\")'}"
            )
        )

    def _validate_code(self, code: str) -> None:
        """验证代码安全性。"""
        if len(code) > self.config.max_code_length:
            raise ValueError(f"代码长度超过限制({self.config.max_code_length}字符)")
        try:
            tree = ast.parse(code)
        except SyntaxError as se:
            raise ValueError(f"语法错误: {se}")

        # 定义禁止使用的语句类型
        forbidden_nodes = (
            ast.AsyncFunctionDef, ast.ClassDef, ast.Delete, ast.Await,
            ast.Yield, ast.YieldFrom, ast.Global
        )
        # 定义禁止调用的危险函数
        dangerous_functions = {"eval", "exec", "__import__"}

        for node in ast.walk(tree):
            # 检查所有的导入语句
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    if module not in self.config.allowed_modules:
                        raise ValueError(f"禁止导入模块: {module}")
            # 检查禁止使用的语句
            elif isinstance(node, forbidden_nodes):
                raise ValueError(f"禁止使用语句: {node.__class__.__name__}")
            # 检查函数调用中是否涉及危险函数
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in dangerous_functions:
                    raise ValueError(f"禁止调用危险函数: {node.func.id}")
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in dangerous_functions:
                        raise ValueError(f"禁止调用危险函数: {node.func.attr}")

    async def execute(self, parameters: Dict[str, Any]) -> str | None:
        """执行Python代码。"""
        code = parameters.get("code", "").strip()
        if not code:
            return "错误：请提供要执行的代码"

        timeout = float(parameters.get("timeout", self.config.timeout))

        try:
            self._validate_code(code)
            # 创建局部命名空间
            local_ns = {}
            stdout = StringIO()
            original_stdout = sys.stdout

            try:
                sys.stdout = stdout
                # 将用户代码编译为RestrictedPython受限字节码
                compiled_code = compile_restricted(
                    code,
                    filename="<user_code>",
                    mode="exec"
                )

                # 设置资源限制（仅在支持的平台上生效）
                if RESOURCE_AVAILABLE:
                    try:
                        # 限制CPU时间
                        resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout))
                        # 限制内存使用，例如限制为100MB
                        resource.setrlimit(resource.RLIMIT_AS, (100 * 1024 * 1024, 100 * 1024 * 1024))
                    except Exception:
                        pass
                else:
                    # 对于不支持resource的系统（如Windows），可以考虑记录日志或使用其他方式进行监控
                    pass

                # 异步执行代码
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: exec(compiled_code, self.safe_globals, local_ns)
                    ),
                    timeout=timeout
                )

                output = stdout.getvalue().rstrip()
                if output:
                    return output
                if "result" in local_ns:
                    return f"结果: {local_ns['result']}"
                return "代码执行完成"

            finally:
                sys.stdout = original_stdout

        except asyncio.TimeoutError:
            return f"错误：代码执行超时(>{timeout}秒)"
        except Exception as e:
            return f"错误：{str(e)}"
