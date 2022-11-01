# 一个基于mirai和graia编写的bot(屎山)
 
## 简易搭建步骤:

1. python3.9+环境,
   mirai:[MCL](https://docs.mirai.mamoe.net/ConsoleTerminal.html)
   并配置[mah](https://docs.mirai.mamoe.net/mirai-api-http/)
2. 在bot根目录下使用
   
   ` pip install -r requirements.txt` 
   
   安装requirements里的依赖
   
   或者其他你喜欢的方式(
3. 在config文件夹内的config文件填写配置信息
4. 点击bot.py运行

~~5.根据报错缺啥弄啥吧(~~

5. 反馈Q群:[749094683](https://jq.qq.com/?_wv=1027&k=1YEq9zks)

### 战地一查询配置默认账号:

1. 在config文件夹内的config文件填写bf1查询默认账号的pid
2. 从ea网站cookie中获取你查询账号的cookie信息:remid和sid
   
   然后在data/battlefield/managerAccount/账号pid/account.json中填入以下信息:
   ```
   {
    "remid":"你的remid",
    "sid":"你的sid"
   }
   ```
3. 其余静态资源请加群下载


