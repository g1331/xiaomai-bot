import ast
import asyncio
import math
from typing import Dict, Any, Set, FrozenSet

from RestrictedPython import compile_restricted
from RestrictedPython.Eval import default_guarded_getitem
from RestrictedPython.Guards import (
    safe_builtins,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
    safer_getattr,
    full_write_guard,
)
# PrintCollector 用于收集用户代码中 print 的输出
from RestrictedPython.PrintCollector import PrintCollector
from RestrictedPython.Utilities import utility_builtins
from loguru import logger
from pydantic import validator

# 你的基础插件类和配置基类，如果不需要可删除/自行调整
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
    max_code_length: int = 5000  # 最大代码长度(字符)

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

        # 时间日期处理（有重复，可以自行去重）
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
        # 系统安全（用户自定义） - 根据需要添加
    })

    # 异步操作限制
    max_async_tasks: int = 5  # 最大并发异步任务数
    max_async_depth: int = 3  # 最大异步嵌套深度
    async_timeout: float = 2.0  # 单个异步任务超时时间

    # 普通函数嵌套深度限制
    max_function_depth: int = 10  # 最大普通函数嵌套深度

    @property
    def required_fields(self) -> Set[str]:
        """检查并移除无法导入的模块。"""
        temp_allowed_modules = list(self.allowed_modules)
        valid_modules = []
        for module_name in temp_allowed_modules:
            try:
                __import__(module_name)
                valid_modules.append(module_name)
            except ImportError:
                logger.warning(f"模块 '{module_name}' 无法导入，将从允许列表中移除")
        self.allowed_modules = frozenset(valid_modules)
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

        collected_output = []

        class MyPrintCollector(PrintCollector):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.printed = collected_output

            def _call_print(self, *values):
                self.printed.append(' '.join(map(str, values)))

        safe_builtins_with_import['_print_'] = MyPrintCollector

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

        # 在 globals 中启用 PrintCollector，用于捕获 print 输出
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
            "_print_": PrintCollector,  # 关键：允许 print 收集
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
            description="在安全沙箱环境中执行Python代码，支持数学和科学计算。",
            parameters={
                "code": f"要执行的Python代码，可用模块包括：{allowed_mods}，可用内置函数包括：{allowed_funcs}",
                "timeout": f"执行超时时间(秒)，默认{self.config.timeout}秒",
            },
            example="{'code': 'import math\\nresult = math.sqrt(16)\\nprint(f\"平方根: {result}\")'}",
        )

    def _validate_code(self, code: str) -> None:
        """验证代码安全性。"""
        if len(code) > self.config.max_code_length:
            raise ValueError(f"代码长度超过限制({self.config.max_code_length}字符)")

        # 解析代码并添加父节点信息
        try:
            tree = ast.parse(code)
        except SyntaxError as se:
            raise ValueError(f"语法错误: {se}")

        # 为每个节点添加 .parent，用于检测函数嵌套深度等
        def add_parent_info(node, parent=None):
            node.parent = parent
            for child in ast.iter_child_nodes(node):
                add_parent_info(child, node)

        add_parent_info(tree)

        # 构建函数调用图
        function_deps = {}
        defined_functions = set()

        class FunctionCallVisitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                defined_functions.add(node.name)
                function_deps[node.name] = set()
                self.generic_visit(node)

            def visit_Call(self, node):
                # 只考虑 f() 形式
                if isinstance(node.func, ast.Name):
                    # 找到上层函数
                    p = node.parent
                    while p:
                        if isinstance(p, ast.FunctionDef):
                            function_deps[p.name].add(node.func.id)
                            break
                        p = getattr(p, 'parent', None)
                self.generic_visit(node)

        FunctionCallVisitor().visit(tree)

        def get_call_depth(func_name, visited=None):
            if visited is None:
                visited = set()

            # 如果再次遇到func_name，说明出现递归或环路
            if func_name in visited:
                # 方案A：返回一个超过 max_depth 的值，让后续判断报错
                return self.config.max_function_depth + 1
                # 或者：raise ValueError(f"检测到函数 {func_name} 存在递归，已超限")

            if func_name not in function_deps:
                # 该函数未在function_deps里登记，表示不调用其他用户函数
                return 0

            visited.add(func_name)
            if not function_deps[func_name]:
                return 0

            # 继续向下递归调用
            return 1 + max(
                get_call_depth(fn, visited.copy()) for fn in function_deps[func_name]
            )

        # 检查每个函数定义的调用链深度
        for func in defined_functions:
            depth = get_call_depth(func)
            if depth > self.config.max_function_depth:
                raise ValueError(
                    f"函数调用链深度超过限制({self.config.max_function_depth})：{func}"
                )

        # 遍历 AST，检查导入、危险函数调用、异步嵌套等
        for node in ast.walk(tree):
            # 检查导入语句
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    if module not in self.config.allowed_modules:
                        raise ValueError(f"禁止导入模块: {module}")
                    if module == 'numpy' and alias.asname == 'np':
                        # numpy -> np 的别名可允许
                        pass

            # 检查自定义禁止的 AST 节点
            if node.__class__.__name__ in self.config.forbidden_nodes:
                raise ValueError(f"禁止使用语句: {node.__class__.__name__}")

            # 检查危险函数调用
            if isinstance(node, ast.Call):
                # 1. 直接调用 name(...)
                if isinstance(node.func, ast.Name) and node.func.id in self.config.dangerous_functions:
                    raise ValueError(f"禁止调用危险函数: {node.func.id}")
                # 2. 模块或对象属性 .func()
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in self.config.dangerous_functions:
                        raise ValueError(f"禁止调用危险函数: {node.func.attr}")

            # 检查异步函数嵌套深度
            if isinstance(node, ast.AsyncFunctionDef):
                depth = 0
                p = node
                while p:
                    if isinstance(p, ast.AsyncFunctionDef):
                        depth += 1
                    p = getattr(p, 'parent', None)
                if depth > self.config.max_async_depth:
                    raise ValueError(
                        f"异步函数嵌套深度超过限制({self.config.max_async_depth})"
                    )

            # 检查普通函数嵌套深度
            if isinstance(node, ast.FunctionDef):
                depth = 0
                p = node
                while p:
                    if isinstance(p, ast.FunctionDef):
                        depth += 1
                    p = getattr(p, 'parent', None)
                if depth > self.config.max_function_depth:
                    raise ValueError(
                        f"普通函数嵌套深度超过限制({self.config.max_function_depth})"
                    )

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

            # 创建执行环境（注意：要 copy 一份，避免多次调用间互相影响）
            env = self.safe_globals.copy()

            # 编译受限字节码
            compiled_code = compile_restricted(code, filename="<user_code>", mode="exec")

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
                # 对于不支持resource的系统（如Windows），可酌情处理
                pass

            # 添加异步运行需要的安全函数
            env.update({
                "asyncio": asyncio,
                "_run_with_async_limits": self._run_with_async_limits,
            })

            # 通过线程池方式执行受限字节码
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: exec(compiled_code, env)
                ),
                timeout=timeout
            )

            # 获取 MyPrintCollector 输出
            collector = env.get("_print_")
            captured_output = "\n".join(collector.printed) if collector and hasattr(collector, "printed") else ""

            # 获取最后一个有效变量的值
            last_value = None
            # env.keys() 至少包含我们注入的安全环境键
            # 如果用户代码中有新变量，可以尝试获取
            if len(env) > 0:
                last_var = list(env.keys())[-1]
                last_value = env[last_var]

            # 根据是否有输出、是否有最后值组合返回
            if captured_output and last_value is not None:
                return f"{captured_output}\n计算结果: {last_value}"
            elif captured_output:
                return captured_output
            elif last_value is not None:
                if isinstance(last_value, str):
                    return f"计算结果: '{last_value}'"
                elif isinstance(last_value, PrintCollector) and hasattr(last_value, "txt"):
                    return f"输出结果: {''.join(last_value.txt)}"
                return f"变量结果: {last_value}"
            else:
                return "无输出结果"

        except asyncio.TimeoutError:
            return f"错误：代码执行超时(>{timeout}秒)"
        except Exception as e:
            return f"错误：{str(e)}"
