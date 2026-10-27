# 大肥鱼私聊助手（astrbot_plugin_dafeiyu_chat）

> **原创**：为大肥鱼定制的 AstrBot 私聊插件  
> **作者**：Grok Bot (Ideas Implementation)  
> **仓库**：https://github.com/JiachengWu-5/astrbot_plugin_dafeiyu_chat

私聊里做两件事：**链接短摘要**，以及 **想看什么就先搜图、搜不到再生图**。

## 功能

1. **链接摘要**  
   私聊发送 / 粘贴 B站或小红书 **纯链接**（`https://…`、`b23.tv/…`、`xhslink.com/…`，或带 BV 号）→ 抓取标题/简介 → LLM 用大肥鱼语气写 2～4 句短摘要。  
   （QQ 分享卡片暂未解析，请发纯链接最稳。）

2. **看图**  
   说「想看看你在吃的栗子」这类意图 → **先搜相关图发一张**；搜不到再按配置尝试生图（如 Ollama 图像模型）。无生图模型时会友好提示，不硬崩。

## 安装

```bash
cd <AstrBot>/data/plugins
git clone https://github.com/JiachengWu-5/astrbot_plugin_dafeiyu_chat
```

或在 AstrBot 插件市场安装「大肥鱼私聊助手」。重载后对 Bot **私聊**测试。

需要 **aiocqhttp** 平台，且 NapCat 能收到私聊。

## 配置

在 AstrBot 插件配置面板：

| 项 | 说明 |
|----|------|
| `enabled` | 总开关 |
| `owner_qq` | 可选；填写后仅该 QQ（及管理员）触发，留空则不限制 |
| `link_summarize.*` | 是否启用摘要、LLM provider、系统提示词 |
| `image.*` | 搜图优先、最大图片字节、生图后端（`stub` / `ollama`）、Ollama 地址与模型 |
| `cache_root` | 缓存目录，默认 `D:\AstrBot\chat_cache`，可改到任意可写路径 |

## 缓存

临时图片下载到 `cache_root/tmp_images`，发送后清理。默认路径是为当前部署写在 D 盘；其他人请在配置里改成自己的目录，**不是硬性要求必须用 D:**。

也可用环境变量 `DAFEIYU_CHAT_CACHE` 覆盖。

## 使用示例

1. 私聊发：`https://www.bilibili.com/video/BVxxxx`
2. 私聊说：`想看看你在吃的栗子`
3. 命令：`私聊助手状态`（查看开关与缓存路径）

## 平台与依赖

- 平台：`aiocqhttp`
- 依赖：标准库为主；环境中已有 Pillow 更佳（见 `requirements.txt`）

## 说明

本插件与「大肥鱼QQ空间」相互独立，互不侵入。
