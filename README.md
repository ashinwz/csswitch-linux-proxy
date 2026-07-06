# CSSwitch Linux Proxy

MacAir 上的 Claude Science 代理 + hostfix 转发。

## 组件

| 文件 | 说明 |
|---|---|
| `proxy/csswitch_proxy.py` | Ark/DeepSeek/Qwen 多 provider 代理 |
| `proxy/hostfix_proxy_v9.py` | 8990→8992 转发，自动 cookie 注入 |
| `config/start.sh` | 一键启动脚本 |
| `config/config.env` | 配置模板 |

## 模型支持

- DeepSeek V4 Pro / V4 Flash
- GLM 5.2（火山方舟 coding-plan）
- Qwen Max / Plus / Turbo

## 端口

- 8990: hostfix proxy（外网访问）
- 8992: Claude Science daemon
- 18991: Ark 代理（Anthropic API 兼容）

## 启动

```bash
cd ~/csswitch
zsh config/start.sh
```
