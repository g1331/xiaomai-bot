<div align="center">

#xiaomai-bot 
<img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt=""/>
<div>一个以<a href="https://github.com/GraiaProject/Ariadne">Graia Ariadne</a>框架为基础的 QQ 机器人</div>
<br>
<div>主要功能服务于战地一战绩查询与服务器管理</div>
<br>
<div>若您在使用过程中发现了bug或有一些建议，欢迎提出ISSUE、PR或加入 <a href="https://jq.qq.com/?_wv=1027&k=1YEq9zks">QQ交流群：749094683</a> </div>
<br>
</div>

----

## 简易搭建:

1. python3.9+环境, mirai:[MCL](https://docs.mirai.mamoe.net/ConsoleTerminal.html) 并配置[mah](https://docs.mirai.mamoe.net/mirai-api-http/)

2. 在bot根目录下使用
   ``` 
   pip install -r requirements.txt
   ```
   安装requirements里的依赖,或者其他你喜欢的方式(
3. 在config文件夹内的config文件填写配置信息
4. 点击bot.py运行

~~5.根据报错缺啥弄啥吧(~~

----

## 战地一查询配置默认账号:

- 在config文件夹内的config文件填写bf1查询默认账号的pid
- 从ea网站cookie中获取你查询账号的cookie信息:remid和sid
   
   - 然后在data/battlefield/managerAccount/账号pid/account.json中填入以下信息:
      ```
      {
       "remid":"你的remid",
       "sid":"你的sid"
      }
      ```
     
- 其余静态资源请加群下载

----

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
