# V3重构plan

---

项目结构:

```

XiaoMaiBot

├─── core               核心-机器人配置/信息

│  ├─── orm             对象关系映射-进行数据库处理

│  │  ├─── __init__.py

│  │  └─── tables.py    内置表

│  └─── ...

│  ├─── saya_modules    规定插件结构-控制开关

│  │  └─── __init__.py

│  └─── ...

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
- [ ] 在n秒内触发n次功能后开始限制
- [ ] cd时间

#### Distribute多账户消息分发:
- [ ] 分发require 

#### 多账户响应模式:
- [ ] 随机响应(默认)
- [ ]   指定bot响应(指定模式)

#### Function功能开关:
- [x] 开关判断->Function.require("模组名")

插件结构:

module.metadata.json:
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
{
    "module_name":{
        "groups": {
            "group_id":{
            	"switch": bool,
                "notice": bool
            }
		},
        "available": bool
    }
}
```

