# Bluetooth Headset Vibe 🎧

> 用你已有的蓝牙耳机，秒变 Vibe Coding 语音控制器。

**不花一分钱**，把蓝牙耳机变成 AI 编程的语音遥控器——按住说话、松开输入、双击发给 AI。

---

## ✨ 工作原理

```
按住耳机键 → 触发微信输入法（/豆包/讯飞）语音输入
松开耳机键 → 语音转文字，自动输入编辑器
双击耳机键 → 把文字发给 Claude，返回编码指令
```

**不用自己造语音识别**，借用现有输入法的成熟语音能力，脚本只负责「监听耳机按键 + 触发快捷键 + 调 AI」。

---

## 🚀 快速开始

### 1. 环境要求

- macOS 12+
- Python 3.10+
- 任意带媒体按键的蓝牙耳机（已配对）
- 微信输入法（或支持语音快捷键的第三方输入法）

### 2. 安装

```bash
git clone https://github.com/starwaysl/bluetooth-headset-vibe.git
cd bluetooth-headset-vibe
pip install -r requirements.txt
```

### 3. 配置

复制 `config.yaml.example` 为 `config.yaml`：

```bash
cp config.yaml.example config.yaml
```

编辑配置：

```yaml
# config.yaml
keyboard_shortcut:
  # 微信输入法的语音输入快捷键（根据你实际设置修改）
  voice_input: "opt+cmd+s"

ai:
  provider: "claude"           # claude / openai / custom
  api_key: "sk-ant-xxx"        # 你的 Claude API Key
  model: "claude-sonnet-4-5"

double_click:
  max_interval_ms: 350         # 双击最大间隔（毫秒）

debug: false
```

### 4. 授权（重要 ⚠️）

脚本需要「辅助功能」权限才能监听和拦截耳机按键：

1. 打开 **系统设置 → 隐私与安全性 → 辅助功能**
2. 点击 **+**，添加你运行脚本的终端（Terminal / iTerm / VS Code）
3. 确保开关打开

> 首次运行时会检测权限并给出提示。

### 5. 运行

```bash
python vibe_click.py
```

看到 `🎧 蓝牙耳机 Vibe 已启动，按住耳机键开始说话...` 就可以用了。

---

## 🎮 操作说明

| 操作 | 效果 |
|---|---|
| **按住耳机键** | 触发语音输入（通过微信输入法） |
| **松开耳机键** | 结束语音，文字自动输入 |
| **双击耳机键** | 复制当前输入框文字 → 发给 Claude → 结果写入剪贴板 |

---

## 🔧 自定义

### 更换输入法

支持任意支持**自定义语音快捷键**的输入法：

- 微信输入法：默认 `⌥⌘S`
- 豆包输入法：在设置里找到语音快捷键
- 讯飞输入法：在设置里找到语音快捷键

修改 `config.yaml` 里的 `voice_input` 字段即可。

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
├── core/
│   ├── event_listener.py      # Quartz Event Tap 监听
│   ├── key_simulator.py       # 键盘模拟
│   ├── voice_trigger.py       # 语音触发逻辑
│   ├── ai_client.py           # Claude/OpenAI API 客户端
│   └── clipboard.py           # 剪贴板操作
└── assets/
    └── demo.gif               # 演示动图（待补）
```

<!-- DEMO_START -->
<!-- 在此插入演示 GIF：建议展示一次完整交互（按住→说话→松开→双击→AI回复） -->
<!-- 推荐大小：宽度 600px，LICEcap 或 Kap 录制 -->
<!-- 上传路径：assets/，文件名 demo.gif -->
<!-- DEMO_END -->

---

## ❓ 常见问题

**Q: 微信输入法的语音快捷键怎么改？**
A: 微信输入法 → 设置 → 快捷键 → 语音输入，改成你喜欢的组合。

**Q: 蓝牙耳机按键没反应？**
A: 确认耳机已连接，且按键默认能控制播放/暂停。不行的话重新配对一次。

**Q: 双击经常误判？**
A: 调整 `config.yaml` 里 `double_click.max_interval_ms`，数值越大越宽松。

**Q: 想用 AirPods？**
A: AirPods 的触摸事件走苹果私有协议，本项目监听的是标准 AVRCP 媒体键。AirPods 标准按键（按一下暂停/播放）可以触发，但长按/双击不支持。

---

## 🗺️ Roadmap

- [ ] v1.0 — MVP：按住录音 + 双击发 Claude
- [ ] v1.1 — 加入「输入法管理器」，自动适配微信/豆包/讯飞
- [ ] v1.2 — Windows / Linux 支持
- [ ] v1.3 — GUI 配置界面
- [ ] v2.0 — 多命令语义（"打开文件 X"、"运行测试" 等）

---

## License

MIT

---

**💡 如果你觉得这个想法有意思，请给一个 Star ⭐，欢迎贡献 PR！**
