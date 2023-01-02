<div align="center">
 
<h1>xiaomai-bot</h1>
<img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt=""/>
<div>一个以<a href="https://github.com/GraiaProject/Ariadne">Graia Ariadne</a>框架为基础的 QQ 机器人</div>
<br>
<div>若您在使用过程中发现了bug或有一些建议，欢迎提出ISSUE、PR或加入 <a href="https://jq.qq.com/?_wv=1027&k=1YEq9zks">QQ交流群：749094683</a> </div>
<br>
</div>

----
## 功能简览:
- 目前支持的主要服务：
    - 重构ing
    
## 简易搭建:

1. python3.10+环境, Mirai:[MCL](https://docs.mirai.mamoe.net/ConsoleTerminal.html) + 配置[MAH](https://docs.mirai.mamoe.net/mirai-api-http/)

2. 安装环境依赖(请先安装poetry)在bot根目录下使用
   ``` 
   poetry install
   ```
3. 在config.yaml文件内填写配置信息
4. 启动bot:poetry run python main.py

~~5.根据报错缺啥弄啥吧(~~



## 鸣谢 & 相关项目
- [`mirai`](https://github.com/mamoe/mirai) & [`mirai-console`](https://github.com/mamoe/mirai-console): 一个在全平台下运行，提供 QQ Android 和 TIM PC 协议支持的高效率机器人框架


感谢 [`GraiaProject`](https://github.com/GraiaProject) 带来的这些项目:

- [`Broadcast Control`](https://github.com/GraiaProject/BroadcastControl): 高性能, 高可扩展性，设计简洁，基于 asyncio 的事件系统
- [`Ariadne`](https://github.com/GraiaProject/Ariadne): 一个设计精巧, 协议实现完备的, 基于 mirai-api-http v2 的即时聊天软件自动化框架
- [`Saya`](https://github.com/GraiaProject/Saya) 简洁的模块管理系统
- [`Scheduler`](https://github.com/GraiaProject/Scheduler): 简洁的基于 `asyncio` 的定时任务实现
- [`Application`](https://github.com/GraiaProject/Application): Ariadne 的前身，一个设计精巧, 协议实现完备的, 基于 mirai-api-http 的即时聊天软件自动化框架

本BOT在开发中参考了如下项目:
- [`SAGIRI BOT`](https://github.com/SAGIRI-kawaii/sagiri-bot): 一个基于 Mirai 和 [Graia-Ariadne](https://github.com/GraiaProject/Ariadne) 的QQ机器人
- [`ABot`](https://github.com/djkcyl/ABot-Graia/): 一个使用 [Graia-Ariadne](https://github.com/GraiaProject/Ariadne) 搭建的 QQ 功能性~~究极缝合怪~~机器人
- [`redbot`](https://github.com/Redlnn/redbot): 一个以 [Graia Ariadne](https://github.com/GraiaProject/Ariadne) 框架为基础的 QQ 机器人

## Stargazers over time

[![Stargazers over time](https://starchart.cc/g1331/xiaomai-bot.svg)](https://starchart.cc/g1331/xiaomai-bot)

# V3重构PJ
框架重构进度:70%

---

项目结构:

```

XiaoMaiBot

├─── core               核心-机器人配置/信息

│  ├─── orm             对象关系映射-进行数据库处理

│  │  ├─── __init__.py

│  │  └─── tables.py    内置表

│  ├─── models          辅助控制组件

│  │  └─── ...

│  ├─── bot.py          机器人核心代码-负责统一调度资源

│  ├─── config.py       机器人配置访问接口

│  ├─── control.py      控制组件-鉴权、开关前置、冷却

│  └─── ...

├─── data               存放数据文件

│  └─── ...

├─── resources          存放项目资源

│  └─── ...

├─── utils              存放运行工具

│  └─── ...

├─── log                机器人日志目录

│  ├─── xxxx-xx-xx

│  │  ├─── common.log   常规日志

│  │  └─── error.log    错误日志

│  └─── ...

├─── modules            机器人插件目录

│  ├─── required        必须插件

│  │  └─── ...

│  ├─── self_contained  内置插件

│  │  └─── ...

│  └─── ...

├─── config.yaml        机器人主配置文件

├─── main.py            应用执行入口

├─── pyproject.toml     项目依赖关系和打包信息

├─── poetry.lock        项目依赖

├─── README.md          项目说明文件

└─── ...  

```

## 核心(core):


### orm:
- [x] AsyncORM


### 配置:
bot基础配置:

- [x] bot_accounts:[]
- [x] default_account
- [x] master_qq
- [x] admins:[]
- [x] host_url
- [x] verify_key


### 控制组件（control）:

#### Permission 权限判断:
- [x] 成员权限判断
- [x] 群权限判断


#### Frequency频率限制:
- [x] current_weight/total_weight


#### Config配置判断:
- [x] require(需要的配置信息)


#### Distribute多账户消息分发:
- [x] 分发require
  
    多账户响应模式:
    - [x] 随机响应(默认)
    - [ ] 指定bot响应(指定模式)


#### Function功能开关:
- [x] 开关判断->Function.require("模组名")

插件结构:

metadata.json:
```json
{
    "level": "插件等级1/2/3",
    "name": "文件名",
    "display_name": "显示名字",
    "version": "0.0.1",
    "author": ["作者"],
    "description": "描述",
    "usage": ["用法"],
    "example": ["例子"],
    "default_switch": true,
    "default_notice": false
}
```

modules:

```python
modules = {
    "module_name": {
        "groups": {
            "group_id": {
                "switch": bool,
                "notice": bool
            }
        },
        "available": bool
    }
}
```


### saya_manager:
- [ ] 插件列表
- [ ] 插件加载
- [ ] 插件重载
- [ ] 已加载插件
- [ ] 未加载插件
- [ ] 开启插件
- [ ] 关闭插件


### perm_manager
- [ ] set user perm     更改用户权限
- [ ] user perm list    查询用户权限
- [ ] set group perm    更改群权限
- [ ] check group perm  查询群权限


### response_manager
- [ ] set group response_type 设定多账户响应模式 随机/指定bot
- [ ] set group account       设定指定响应bot
