# Bluetooth Headset Vibe 🎧

> 用**蓝牙遥控器**（或任意蓝牙 HID 设备），秒变 Vibe Coding 语音控制器。

**不花一分钱**（如果你已有蓝牙遥控器），把遥控器变成 AI 编程的语音遥控器——按回车说话、松开输入、按 F5 发给 AI。

---

## ✨ 工作原理

```
按回车（或你设定的键）   → 触发微信输入法（/豆包/讯飞）语音输入
松开回车                 → 语音转文字，自动输入编辑器
按 F5（或你设定的键）    → 把文字发给 Claude，返回编码指令
```

**不用自己造语音识别**，借用现有输入法的成熟语音能力，脚本只负责「监听遥控器按键 + 触发快捷键 + 调 AI」。

---

## 🎮 为什么用蓝牙遥控器而不是蓝牙耳机？

市面上很多蓝牙耳机（如 Redmi Buds 7S、AirPods）的触摸按键走的是**媒体控制协议（AVRP）**，被 macOS 底层直接消费，**任何用户态软件都监听不到**。

蓝牙遥控器（如小米电视遥控器）走的是**标准 HID 键盘协议**，macOS 原生识别，按键事件 100% 可监听。

> 而且小米电视遥控器自带**麦克风**，一个设备 = 按键 + 麦克风，完美。

---

## 🚀 快速开始

### 1. 环境要求

- macOS 12+
- Python 3.10+
- 蓝牙遥控器（小米电视遥控器 4A/4C/4S 等，**带麦克风的版本**）
- 微信输入法（或支持语音快捷键的第三方输入法）

### 2. 安装

```bash
git clone https://github.com/starwaysl/bluetooth-headset-vibe.git
cd bluetooth-headset-vibe
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 配对蓝牙遥控器

1. 遥控器装电池
2. 进入配对模式（**长按 OK 键 10 秒**，指示灯快速闪烁）
3. Mac 上：**系统设置 → 蓝牙 → 找到"小米遥控器" → 连接**
4. 连接成功后，遥控器变成蓝牙键盘 + 蓝牙音频输入设备

### 4. 配置

复制 `config.yaml.example` 为 `config.yaml`：

```bash
cp config.yaml.example config.yaml
```

编辑配置：

```yaml
# config.yaml
triggers:
  # 哪个键触发语音输入（用 probe_remote.py 探测）
  voice_input: "Key.enter"      # 回车键
  # 哪个键发给 AI
  send_to_ai: "Key.f5"           # F5 键

keyboard_shortcut:
  # 微信输入法的语音输入快捷键（根据你实际设置修改）
  voice_input: "opt+cmd+s"

ai:
  provider: "claude"
  api_key: "sk-ant-xxx"          # 你的 Claude API Key
  model: "claude-sonnet-5"

debug: false
```

### 5. 运行

```bash
python vibe_click.py
```

看到 `🎧 Bluetooth Headset Vibe 已启动` 就可以用了。

---

## 🎯 操作说明

| 操作 | 效果 |
|---|---|
| **按回车键** | 触发语音输入（通过微信输入法） |
| **松开回车键** | 结束语音，文字自动输入编辑器 |
| **按 F5 键** | 复制当前输入框文字 → 发给 Claude → 结果写入剪贴板 |

---

## 🔧 自定义

### 更换触发键

1. 运行探测器找出你的遥控器按键 keyCode：

```bash
python probe_remote.py
```

2. 按遥控器，终端会显示 keyCode（如 `Key.f5`、`Key.enter`）
3. 把 keyCode 填进 `config.yaml` 的 `triggers` 部分

### 更换输入法

支持任意支持**自定义语音快捷键**的输入法：

- 微信输入法：默认 `⌥⌘S`
- 豆包输入法：在设置里找到语音快捷键
- 讯飞输入法：在设置里找到语音快捷键

修改 `config.yaml` 里的 `keyboard_shortcut.voice_input` 字段即可。

### 更换 AI 后端

```yaml
ai:
  provider: "openai"
  api_key: "sk-xxx"
  model: "gpt-4o"
```

---

## 📂 项目结构

```
bluetooth-headset-vibe/
├── README.md
├── config.yaml.example
├── requirements.txt
├── vibe_click.py              # 主入口
├── probe_remote.py            # 遥控器按键探测器
├── core/
│   ├── key_simulator.py       # 键盘模拟（pynput）
│   ├── ai_client.py           # Claude/OpenAI API 客户端
│   └── clipboard.py           # 剪贴板操作
└── assets/
    └── demo.gif               # 演示动图（待补）
```

---

## ❓ 常见问题

**Q: 小米电视遥控器怎么重置蓝牙？**
A: 拔电池 → 装回 → 长按 OK 键 10 秒 → 指示灯闪烁 → 重新配对。

**Q: 按键没反应？**
A: 运行 `python probe_remote.py`，按遥控器看有没有输出。没有输出说明配对失败，重新配对。

**Q: 微信输入法的语音快捷键怎么改？**
A: 微信输入法 → 设置 → 快捷键 → 语音输入，改成你喜欢的组合。

**Q: 蓝牙耳机可以吗？**
A: 大部分蓝牙耳机（AirPods、Redmi Buds 等）的触摸按键走媒体控制协议，macOS 上层软件**监听不到**。推荐用蓝牙遥控器。

---

## 🗺️ Roadmap

- [x] v1.0 — MVP：pynput 监听 + 蓝牙遥控器支持
- [ ] v1.1 — 加入「输入法管理器」，自动适配微信/豆包/讯飞
- [ ] v1.2 — Windows / Linux 支持
- [ ] v1.3 — GUI 配置界面
- [ ] v2.0 — 多命令语义（"打开文件 X"、"运行测试" 等）

---

## License

MIT

---

**💡 如果你觉得这个想法有意思，请给一个 Star ⭐，欢迎贡献 PR！**
