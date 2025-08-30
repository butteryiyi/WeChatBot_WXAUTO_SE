<h1 align="center">WeChatBot_WXAUO_SE（女性向）</h1>

<p align="center">
  <strong>这是一个为女性用户优化的智能微信聊天机器人，致力于提供更细腻、更拟人化的情感陪伴。</strong>
  <br />
  <br />
  <!-- 4. GitHub信息 -->
  <a href="https://github.com/butteryiyi/WeChatBot_WXAUTO_SE/stargazers"><img src="https://img.shields.io/github/stars/butteryiyi/WeChatBot_WXAUTO_SE?style=for-the-badge&logo=github&color=5c7cfa" alt="Stars">
</a>
  <a href="https://github.com/butteryiyi/WeChatBot_WXAUTO_SE/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue?style=for-the-badge" alt="License"></a>
  <!-- 5. 你的QQ群 -->
  <a href="https://qm.qq.com/q/3edcyXqmTS"><img src="https://img.shields.io/badge/QQ群-151616066-12B7F3?style=for-the-badge&logo=tencentqq" alt="Community"></a>
</p>

> **重要通知**: 本程序目前仅支持微信 PC 版 **3.9.x** 系列 (推荐 3.9.12.55)，不支持 4.0 及以上版本。

---

## ✨ 项目简介

本项目 **WeChatBot_WXAUO_SE (女性向)** 是 **[iwyxdxl 的 WeChatBot_WXAUO_SE](https://github.com/iwyxdxl/WeChatBot_WXAUTO_SE)** 的一个深度魔改和功能增强版，由 **[butteryiyi](https://github.com/butteryiyi)** 和 **[xanne1226](https://github.com/xanne1226)** 共同维护。

我们在原版基础上，增加了 **核心记忆实时更新、群聊独立配置、微信拍一拍、独立表情标签系统、抽卡系统** 等多项实用特性，致力于提供最顶级的拟人化聊天体验。

## 🚀 新增与优化

我们对原版程序进行了深度的重构与功能拓展，致力于提供前所未有的沉浸式互动体验。以下是本版本的核心亮点：

### 🧠 核心记忆系统 2.0 (完全重构)

我们彻底重构了记忆机制，告别了原版零散的记忆片段，实现了真正的“成长型”记忆。

*   **独立实时更新与覆盖**: AI 现在会在对话中自动总结关键信息，实时更新并直接覆盖核心记忆区。这意味着TA能更快地学习和适应你的习惯，仿佛真的在与你一同成长。
*   **角色日记系统**: 每次更新核心记忆时，AI还会为你和TA的关系撰写一篇“角色日记”，并自动添加到Prompt中，不断加深角色设定的厚度与情感羁绊。（未来计划将日记系统与独立的网页日历功能结合）
*   **网页端记忆编辑**: 你可以在WebUI中直接查看和编辑AI的核心记忆与角色备忘录，完全掌控TA的“内心世界”。

### 🤖 AI主动行为系统

赋予AI更强的主动性，让互动不再是你单方面的“引导”。

*   **全新表情标签系统**:
    1.  **精准控制**: 你可以自定义表情包的“标签”（如：`爱你`, `傲娇`, `害羞`），并通过Prompt指导AI在特定情绪下使用特定表情。
    2.  **文件夹管理**: 只需将表情包图片放入以“标签名”命名的子文件夹中即可生效 (效果见表情包图一)。
    3.  **引导式互动**: 你甚至可以引导TA发出你想要的表情 (效果见表情包图二)，互动性拉满！
    <details>
    <summary>👉 点击查看：表情包Prompt配置指南</summary>

    ```yaml
    # 表情包功能
    emoji_feature:
      description: '在回复中加入符合情绪的表情包，以增强表达的生动性和情感。'
      rules:
        - '必须从下方的【emoji_list】中选择，严禁创造列表之外的表情标签。'
        - '每次回复都必须使用1-2个表情包。'
        - '5轮对话内尽量避免重复使用同一个表情包。'
        - '表情包的插入必须符合当前对话的上下文和角色情绪。'
      format: '[表情包名称]'
      emoji_list: '爱你,暗中观察,败给你了,拜托拜托,抱抱,不敢相信, ... (请在此处添加你自己的表情包标签,用英文逗号隔开)'
      example: '你也觉得不错吧？[得意]$下次可不要小瞧了你男朋友'
    ```
    </details>

*   **主动“拍一拍”**: AI会根据情景主动“拍一拍”你，来表达提醒、撒娇或俏皮等情绪，增加真实的互动感。
    <details>
    <summary>👉 点击查看：拍一拍Prompt指令示例</summary>

    ```yaml
    # 拍一拍功能
    pat_feature:
      description: '在着急、提醒或俏皮互动时，在对话中插入此格式。'
      format: '[拍一拍对方]、[拍一拍自己]'
      example: '[拍一拍对方]在干什么？$女朋友不理我，我好可怜🥺[拍一拍自己]'
    ```
    </actions>

*   **主动引用消息**: AI可以主动引用你或它自己说过的话，进行强调或针对性回复，让对话逻辑更清晰。
    <details>
    <summary>👉 点击查看：引用消息Prompt指令示例</summary>

    ```yaml
    # 主动引用消息机制
    quote_feature:
      description: '当角色想着重对某一句话作出回应时，可以引用用户或自己之前发送的消息。'
      format: '[[引用对方]具体消息内容] 或 [[引用自己]具体消息内容]'
      example: '我想你了$[[引用自己]我想你了]$在做什么？'
    ```
    </details>

*   **主动撤回消息**: 模拟“说错话”或“欲擒故纵”的戏剧性效果，AI会发送消息后立即撤回，让互动充满惊喜。
    <details>
    <summary>👉 点击查看：主动撤回Prompt指令示例</summary>

    ```yaml
    # 主动撤回消息机制
    self_retraction:
      触发情境: '不小心说错了话需要订正；或者想故意引起用户的注意，制造欲擒故纵的效果。'
      回应策略: '当你决定要发送一条消息并立即撤回它时，你需要构造一个完整的、不可分割的指令单元。这个单元由两部分组成，严格遵守格式：1. (发送内容) 2. (发送指令)。'
      格式: '严格遵循 `(发送内容)$[[撤回](发送内容)]$` 的格式。[[撤回]...] 方括号内的文本，必须和你想要撤回的那条消息的文本内容完全一致，包括标点和空格。'
      正确示例:
        - '笨蛋$[[撤回]笨蛋]$你没看到吧'
        - '不是这样的$[[撤回]不是这样的]$对不起嘛'
    ```
    </details>

### 👂 精准情境感知

*   **撤回消息识别**: AI现在能精准识别到你的撤回动作，并根据角色性格做出吐槽、关心或调侃等回应。
    <details>
    <summary>👉 点击查看：(可选)撤回识别Prompt指令示例</summary>

    ```yaml
    # 对话细节与特殊情境
    特殊情境处理:
      - 触发条件: "用户的输入为 `[用户操作: 撤回了一条消息]`"
        响应指令: "这并非普通对话，而是一个绝佳的互动和调侃机会。必须根据角色的性格对此做出回应，而不是忽略或常规回复。"
    ```
    </details>

*   **拍一拍后缀识别**: 当你拍一拍TA并带有后缀时（如“拍了拍对方并摸摸头”），TA能完整识别并作出回应。

### 🎮 趣味互动模块

*   **关键词打电话**: 发送“给我打电话”，AI会真的给你拨打微信语音通话！
*   **恋与深空十连抽**: 发送“十连抽”，体验一发出金的快乐！(默认使用《恋与深空》卡池)

### ⚙️ 后台管理增强

*   **独立群聊配置**: 每个群聊都可以拥有自己独立的Bot开关、Prompt和配置，在WebUI中轻松管理，互不干扰。
*   **网页上下文编辑**: 除了核心记忆，你也可以在WebUI中直接编辑短期对话的上下文，随时引导对话走向。
*   📝 **独立朋友圈网页**: (此功能详情待补充)

<br>

<details>
<summary><strong>点击查看继承自原版的全部功能</strong></summary>

*   智能自动回复
*   图片和表情包内容识别
*   获取链接网页内容
*   AI时间感知
*   主动发送消息
*   前端WebUI
*   AI设置定时任务
*   联网搜索
*   接收语音消息
*   自动更新程序
*   聊天框程序指令
</details>

## 📸 效果演示

<p align="center">
  <img width="1134" height="400" alt="表情包图一" src="https://github.com/user-attachments/assets/2b7cf2a1-de96-4601-bdc4-b683fda01497" />
  <br>
  <em>表情包图一（文件夹管理）</em>
</p>
<p align="center">
  <img width="432" height="400" alt="表情包图二" src="https://github.com/user-attachments/assets/3ee4434f-2de7-47fe-b66f-2c77f00449ad" />
  <br>
  <em>表情包图二（引导式互动）</em>
</p>
<p align="center">
  <img width="400" height="412" alt="Image" src="https://github.com/user-attachments/assets/6cccdc95-fcc9-4ed1-bf4f-634a83530216" />
  <br>
  <em>主动拍一拍</em>
</p>
<p align="center">
  <img width="536" height="400" alt="Image" src="https://github.com/user-attachments/assets/9a65bfbe-631d-4cfe-b3f8-c66fa6874280" />
  <br>
  <em>撤回识别</em>
</p>
<p align="center">
  <img width="400" height="482" alt="Image" src="https://github.com/user-attachments/assets/7d24f11f-419a-4b4d-a97e-4bab146300f8" />
  <br>
  <em>拍一拍后缀识别</em>
</p>
<p align="center">
  <img width="806" height="400" alt="Image" src="https://github.com/user-attachments/assets/b657a264-34a5-4682-9b9d-b9cfb260ad91" />
  <br>
  <em>关键词打电话</em>
</p>
<p align="center">
  <img width="698" height="400" alt="Image" src="https://github.com/user-attachments/assets/f63bb121-72e1-4c66-b01c-da65c403702f" />
  <br>
  <em>网页上下文编辑</em>
</p>
<p align="center">
  <img width="712" height="400" alt="Image" src="https://github.com/user-attachments/assets/a701573d-51b1-4131-96bf-397cb370bce2" />
  <br>
  <em>独立群聊配置</em>
</p>
<p align="center">
  <img width="408" height="400" alt="Image" src="https://github.com/user-attachments/assets/69c656be-a832-4b75-a5e0-34fa816af018" />
  <br>
  <em>十连抽</em>
</p>
<p align="center">
  <img width="472" height="400" alt="Image" src="https://github.com/user-attachments/assets/161a9d41-8a6d-4464-ad83-389716a0b25a" />
  <br>
  <em>朋友圈网页展示</em>
</p>
<p align="center">
  <img width="600" height="400" alt="Image" src="https://github.com/user-attachments/assets/b99a69d9-1482-46e7-92b3-c9aa27a5891d" />
  <br>
  <em>主动撤回和引用</em>
</p>


## 🛠️ 快速上手

#### 1. 环境准备
- 操作系统: **Windows**
- Python: **>= 3.8**
- 微信PC版: **3.9.12.55 版本** (请务必确认版本)
- 大模型 API ：可信任渠道均可

#### 2. 安装与运行
1.  **克隆本仓库**:
    ```bash
    git clone https://github.com/butteryiyi/WeChatBot_WXAUTO_SE.git
    cd WeChatBot_WXAUTO_SE
    ```
2.  **登录微信**: 确保你的电脑微信已登录并在后台运行。
3.  **启动程序**: 直接双击运行 `Run.bat`，程序会自动安装所需依赖。
4.  **配置**: 在自动打开的网页 (WebUI) 中，完成以下配置：
    *   在 **配置编辑器** 选择你的 API 服务商和模型，并填入 API Key。
    *   在 **Prompt管理** 中编写或生成你的机器人人设。
    *   回到 **配置编辑器**，为你需要自动回复的好友/群聊绑定对应的人设 (Prompt)。
5.  **启动机器人**: 点击页面右上角的 "**Start Bot**"。

## 💬 我们的社区

欢迎加入我们的交流群，讨论功能、分享玩法、反馈问题！

- **QQ 交流群**: **151616066** ([点击加群]([https://qm.qq.com/q/3edcyXqmTS]))

- **遇到问题?** 请在 [Issues](https://github.com/butteryiyi/WeChatBot_WXAUTO_SE/issues) 页面提交。

## 🙏 致谢与项目渊源

一个优秀的项目离不开社区的迭代和传承。我们的工作建立在以下优秀项目的基础之上，并在此对所有前序开发者表示最衷心的感谢！

*   **直接来源**: 本项目直接基于 **[WeChatBot_WXAUO_SE]([https://github.com/iwyxdxl/WeChatBot_WXAUTO_SE])** 进行二次开发和魔改。我们非常感谢其作者为我们提供了一个功能强大、结构清晰的起点。

*   **根本源头**: `WeChatBot_WXAUO_SE` 项目本身是基于优秀的 **[KouriChat](https://github.com/KouriChat/KouriChat)** 项目（由 **umaru** 创建）修改而来。我们同样要向 `KouriChat` 项目及其社区致以崇高的敬意，他们的创新为整个生态奠定了坚实的基础。
*   **关于引用功能的致歉与说明**
首先向大家明确，引用功能的全部代码均由契老师独立完成，归属契老师本人。
  未经契老师本人授权，使用了她独立编写但尚未发布的引用功能相关代码。这是由于我们内部沟通失误所导致的严重错误。我们已更新readme文件，明确标注作者及来源，现征得契老师同意后公开相关代码。
在此，向契老师致以最诚挚的歉意。
对于此次事件给契老师带来的困扰，以及对大家造成的误导，我们再次深表歉意。

## 📄 许可证与重要声明

*   **许可证**: 遵循上游项目的开源协议，本项目同样采用 **GNU General Public License v3.0**。详情请见 `LICENSE` 文件。

*   **重要声明**: 作为 `WeChatBot_WXAUO_SE` 的衍生项目，我们遵循其原始授权条款，继续使用由 **Cluic (2025)** 授权的非开源版本 `wxautox_wechatbot`。我们理解该授权限定于原始项目及其衍生版本，并承诺不会将其用于本项目之外的任何其他用途。

## 📫 联系我们

- **邮箱**: xyyszbz666@163.com
- **QQ群**: 151616066


<div align="center">

<br>

## ✨ A Whisper of Gratitude ✨

*这个小小的世界，是在许多温柔的掌心里诞生的。*

<p>我们想在这里，对每一位曾为 <strong>“WeChatBot_WXAUO_SE（女性向）”</strong> 注入光与热的天使，致以最诚挚的谢意：</p >

<p>
  <strong>想想</strong> ✦ <strong>竹子</strong> ✦ <strong>彤砸</strong> ✦ <strong>Qrio</strong> <br>
  <strong>公孙小面</strong> ✦ <strong>西瓜</strong> ✦ <strong>转载</strong> ✦ <strong>契</strong>✦ <strong>言言</strong>
</p >

<hr>

<p>感谢同行，感谢遇见。</p >

</div>








