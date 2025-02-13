import ast
import asyncio
import math
import sys
from io import StringIO
from typing import Dict, Any, Set, FrozenSet

from RestrictedPython import compile_restricted
from RestrictedPython.Eval import default_guarded_getitem
from RestrictedPython.Guards import safe_builtins, guarded_iter_unpack_sequence, guarded_unpack_sequence, safer_getattr, full_write_guard
from RestrictedPython.Utilities import utility_builtins
from loguru import logger
from pydantic import validator

from ..core.plugin import BasePlugin, PluginConfig, PluginDescription

# 尝试导入resource模块，Windows平台通常不支持
try:
    import resource

    RESOURCE_AVAILABLE = True
except ImportError:
    RESOURCE_AVAILABLE = False


class CodeRunnerConfig(PluginConfig):
    """代码执行插件配置类
    
    配置项包括：
    1. 基本限制：超时时间、代码长度等
    2. 允许的模块：可以导入的Python模块列表
    3. 允许的内置函数：可以使用的Python内置函数
    4. 危险函数黑名单：禁止使用的函数
    5. 禁止的语法节点：不允许使用的Python语法结构
    """

    # 基本执行限制
    timeout: int = 5  # 执行超时时间(秒)
    max_code_length: int = 1000  # 最大代码长度(字符)

    # 允许导入的模块白名单
    allowed_modules: FrozenSet[str] = frozenset({
        # 基础数学计算
        "math",  # 基础数学函数(sin, cos, sqrt等)
        "cmath",  # 复数数学运算
        "decimal",  # 高精度十进制计算
        "fractions",  # 分数运算
        "numbers",  # 数字抽象基类
        "random",  # 随机数生成
        "statistics",  # 基础统计计算

        # 科学计算
        "numpy",  # NumPy科学计算库
        "scipy",  # SciPy科学计算库

        # 数据结构和算法
        "collections",  # 容器数据类型
        "array",  # 数组操作
        "heapq",  # 堆队列算法

        # 工具函数
        "itertools",  # 迭代器工具
        "functools",  # 高阶函数工具

        # 时间日期处理
        "time",  # 时间处理
        "calendar",  # 日历相关功能

        # 字符串处理
        "string",  # 字符串常量和模板
        "re",  # 正则表达式

        # 时间日期处理
        "datetime",  # 日期和时间处理
        "calendar",  # 日历相关功能

        # 数据交换格式
        "json",  # JSON数据处理
    })

    # 允许使用的内置函数白名单
    allowed_builtins: FrozenSet[str] = frozenset({
        # 数学运算
        'abs', 'min', 'max', 'sum', 'len', 'round', 'pow', 'divmod',

        # 类型转换
        'int', 'float', 'str', 'bool', 'complex',

        # 序列操作
        'sorted', 'reversed', 'enumerate', 'zip', 'any', 'all',

        # 字符处理
        'chr', 'ord',

        # 类型检查
        'isinstance', 'issubclass', 'hasattr', 'callable',

        # 进制转换
        'bin', 'oct', 'hex', 'format'
    })

    # 危险函数黑名单
    dangerous_functions: FrozenSet[str] = frozenset({
        # 代码执行
        "eval", "exec", "compile", "__import__",  # 防止代码注入

        # 系统操作
        "system", "popen", "spawn", "fork",  # 防止执行系统命令
        "subprocess", "os", "sys", "platform",  # 防止系统操作

        # 文件操作
        "open", "file", "read", "write",  # 防止文件访问
        "remove", "unlink", "chmod", "chown",  # 防止文件系统操作

        # 进程和线程
        "Process", "Thread", "Pool", "_thread",  # 防止并发操作
        "multiprocessing", "threading", "concurrent",  # 防止并发操作
        "kill", "terminate", "exit", "abort",  # 防止进程操作

        # 反射和内省
        "__dict__", "__class__", "__bases__",  # 防止反射攻击
        "__subclasses__", "__mro__", "__code__",
        "__globals__", "getattr", "setattr",

        # 其他危险操作
        "breakpoint", "globals", "locals",  # 防止调试和内省
        "vars", "dir", "gc", "memoryview",  # 防止内存操作
        "weakref", "reload"  # 防止内存和模块操作
    })

    # 禁止的AST节点类型
    forbidden_nodes: FrozenSet[str] = frozenset({
        # 系统安全（用户自定义）
    })

    # 异步操作限制
    max_async_tasks: int = 5  # 最大并发异步任务数
    max_async_depth: int = 3  # 最大异步嵌套深度
    async_timeout: float = 2.0  # 单个异步任务超时时间

    # 普通函数嵌套深度限制
    max_function_depth: int = 10  # 最大普通函数嵌套深度

    @property
    def required_fields(self) -> Set[str]:
        temp_allowed_modules = list(self.allowed_modules)
        for module_name in temp_allowed_modules:
            try:
                __import__(module_name)
            except ImportError:
                logger.warning(f"模块 '{module_name}' 无法导入，将从允许列表中移除")
                temp_allowed_modules.remove(module_name)
        self.allowed_modules = frozenset(temp_allowed_modules)
        return set()

    def dict(self, *args, **kwargs):
        """重写dict方法，确保Set被序列化为list"""
        d = super().dict(*args, **kwargs)
        # 将Set转换为list以便JSON序列化
        d['allowed_modules'] = list(self.allowed_modules)
        d['allowed_builtins'] = list(self.allowed_builtins)
        d['dangerous_functions'] = list(self.dangerous_functions)
        d['forbidden_nodes'] = list(self.forbidden_nodes)
        return d

    @validator('allowed_modules', 'allowed_builtins', 'dangerous_functions', 'forbidden_nodes', pre=True)
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
        self._active_tasks = 0
        self._async_depth = 0

        # 定义安全的导入函数
        def safe_import(name, *args, **kwargs):
            if name not in self.config.allowed_modules:
                root_module = name.split('.')[0]
                if root_module not in self.config.allowed_modules:
                    raise ImportError(f"模块 '{name}' 不在允许列表中")
            return __import__(name, *args, **kwargs)

        # 将安全导入函数加入到内置函数中
        safe_builtins_with_import = dict(safe_builtins)
        safe_builtins_with_import['__import__'] = safe_import

        # 配置安全环境
        def _inplacevar_(op, x, y):
            """处理就地运算符，如 +=, -=, *=, /= 等"""
            if op == '+=':
                return x + y
            elif op == '-=':
                return x - y
            elif op == '*=':
                return x * y
            elif op == '/=':
                return x / y
            elif op == '//=':
                return x // y
            elif op == '%=':
                return x % y
            elif op == '**=':
                return x ** y
            elif op == '<<=':
                return x << y
            elif op == '>>=':
                return x >> y
            elif op == '&=':
                return x & y
            elif op == '^=':
                return x ^ y
            elif op == '|=':
                return x | y
            raise NotImplementedError(f'不支持的就地运算符: {op}')

        self.safe_globals = {
            "__builtins__": safe_builtins_with_import,  # 使用包含 __import__ 的内置函数
            "_getattr_": safer_getattr,
            "_getitem_": default_guarded_getitem,
            "_iter_unpack_sequence_": guarded_iter_unpack_sequence,
            "_unpack_sequence_": guarded_unpack_sequence,
            "_getiter_": iter,  # 基本迭代器控制
            "_write_": full_write_guard,  # 写入操作控制
            "_inplacevar_": _inplacevar_,  # 就地运算符支持
            "math": math,
            **utility_builtins
        }
        
        # 预加载允许的模块到安全环境
        temp_allowed_modules = list(self.config.allowed_modules)
        for mod_name in temp_allowed_modules[:]:
            try:
                module = __import__(mod_name)
                # 存储完整模块
                self.safe_globals[mod_name] = module
                # 处理常用的模块别名
                if mod_name == 'numpy':
                    self.safe_globals['np'] = module
            except ImportError:
                logger.warning(f"模块 '{mod_name}' 无法导入，将从允许列表中移除")
                temp_allowed_modules.remove(mod_name)
        
        self.config.allowed_modules = frozenset(temp_allowed_modules)

    @property
    def description(self) -> PluginDescription:
        allowed_mods = ", ".join(sorted(list(self.config.allowed_modules)[:5])) + "..."
        allowed_funcs = ", ".join(sorted(list(self.config.allowed_builtins)[:5])) + "..."

        return PluginDescription(
            name="code_runner",
            description="Python代码安全沙箱执行环境\n"
                        "- 支持数学/科学计算\n"
                        "- 内置安全限制\n"
                        f"- 代码上限:{self.config.max_code_length}字符\n"
                        f"- 超时限制:{self.config.timeout}秒",
            parameters={
                "code": f"Python代码\n可用模块:{allowed_mods}\n可用函数:{allowed_funcs}",
                "timeout": f"执行超时(秒),默认{self.config.timeout}"
            },
            example=(
                "基础数学计算示例：\n"
                "{'code': 'import math\\n"
                "import numpy as np\\n"
                "# 计算正弦函数和数组操作\\n"
                "x = np.linspace(0, 2*math.pi, 5)\\n"
                "y = np.sin(x)\\n"
                "print(f\"x点: {x}\\ny值: {y}\")'}"
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

        # 构建函数调用图
        function_deps = {}
        defined_functions = set()
        
        class FunctionCallVisitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                defined_functions.add(node.name)
                function_deps[node.name] = set()
                # 访问函数体
                self.generic_visit(node)
            
            def visit_Call(self, node):
                if isinstance(node.func, ast.Name):
                    # 获取当前所在的函数上下文
                    for parent in ast.walk(tree):
                        if isinstance(parent, ast.FunctionDef) and any(node in ast.walk(parent) for node in ast.walk(node)):
                            function_deps[parent.name].add(node.func.id)
                            break
                self.generic_visit(node)

        # 遍历AST构建调用图
        FunctionCallVisitor().visit(tree)

        # 检查函数调用链深度
        def get_call_depth(func_name, visited=None):
            if visited is None:
                visited = set()
            if func_name in visited:
                return 0  # 避免循环调用
            if func_name not in function_deps:
                return 0
            visited.add(func_name)
            if not function_deps[func_name]:
                return 0
            return 1 + max((get_call_depth(f, visited.copy()) for f in function_deps[func_name]), default=0)

        # 检查每个函数的调用链深度
        for func in defined_functions:
            depth = get_call_depth(func)
            if depth > self.config.max_function_depth:
                raise ValueError(f"函数调用链深度超过限制({self.config.max_function_depth})：{func}")

        async_funcs = []
        for node in ast.walk(tree):
            # 检查所有的导入语句，同时处理别名
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    if module not in self.config.allowed_modules:
                        raise ValueError(f"禁止导入模块: {module}")
                    # 如果是numpy的别名导入，确保允许
                    if module == 'numpy' and alias.asname == 'np':
                        continue

            # 检查禁止使用的语句
            elif node.__class__.__name__ in self.config.forbidden_nodes:
                raise ValueError(f"禁止使用语句: {node.__class__.__name__}")

            # 检查函数调用中是否涉及危险函数
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.config.dangerous_functions:
                    raise ValueError(f"禁止调用危险函数: {node.func.id}")
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in self.config.dangerous_functions:
                        raise ValueError(f"禁止调用危险函数: {node.func.attr}")

            if isinstance(node, ast.AsyncFunctionDef):
                async_funcs.append(node.name)
                # 检查异步函数的嵌套深度
                depth = 0
                parent = node
                while parent:
                    if isinstance(parent, ast.AsyncFunctionDef):
                        depth += 1
                    parent = getattr(parent, 'parent', None)
                if depth > self.config.max_async_depth:
                    raise ValueError(f"异步函数嵌套深度超过限制({self.config.max_async_depth})")

            # 新增：对普通函数的嵌套深度检测
            if isinstance(node, ast.FunctionDef):
                depth = 0
                parent = node
                while parent:
                    if isinstance(parent, ast.FunctionDef):
                        depth += 1
                    parent = getattr(parent, 'parent', None)
                if depth > self.config.max_function_depth:
                    raise ValueError(f"普通函数嵌套深度超过限制({self.config.max_function_depth})")

    async def _run_with_async_limits(self, coro):
        """运行异步代码并实施限制。"""
        if self._active_tasks >= self.config.max_async_tasks:
            raise RuntimeError(f"并发异步任务数超过限制({self.config.max_async_tasks})")

        self._active_tasks += 1
        try:
            return await asyncio.wait_for(coro, timeout=self.config.async_timeout)
        finally:
            self._active_tasks -= 1

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

                # 异步支持相关的安全函数到环境中
                self.safe_globals.update({
                    "asyncio": asyncio,
                    "_run_with_async_limits": self._run_with_async_limits,
                })

                # 异步执行代码
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: exec(compiled_code, self.safe_globals, local_ns)
                    ),
                    timeout=timeout
                )

                output = stdout.getvalue().rstrip()
                # 获取最后一个有效变量的值
                last_value = None
                if local_ns:
                    # 尝试获取最后一个变量的值
                    last_var = list(local_ns.keys())[-1]
                    last_value = local_ns[last_var]

                if output and last_value is not None:
                    return f"{output}\n计算结果: {last_value}"
                elif output:
                    return output
                elif last_value is not None:
                    return f"计算结果: {last_value}"
                return "代码执行完成"

            finally:
                sys.stdout = original_stdout

        except asyncio.TimeoutError:
            return f"错误：代码执行超时(>{timeout}秒)"
        except Exception as e:
            return f"错误：{str(e)}"
