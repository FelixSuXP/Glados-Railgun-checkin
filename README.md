# Glados自动签到

> 基于 GitHub Actions 的 GLaDOS 自动签到工具，支持多账号与多通道推送（PushDeer / Server酱 / 企业微信）。

## 文件结构

```shell
│  checkin.py          # 签到主脚本
│  logging_config.py   # 日志配置（北京时间、[I/W/E] 短标签）
│  requirements.txt    # Python 依赖
│
├─.github
│  └─workflows
│          gladosCheck.yml   # Actions 配置文件
```

## 食用方式

### 注册 GLaDOS 账号

注册地址：<https://glados.space/landing/0A58E-NV28S-6U3QV-33VMG>

- 我的邀请码：[`0A58E-NV28S-6U3QV-33VMG`](https://0a58e-nv28s-6u3qv-33vmg.glados.space)
- 我的优惠码（9 折）：[`DEVILSTORE`](https://0a58e-nv28s-6u3qv-33vmg.glados.space)

### Fork 本仓库

![图片加载失败](imgs/1.png)

### 配置 Secrets

跳转至自己仓库的 `Settings` → `Secrets and variables` → `Action`，按需添加以下 `repository secret`：

#### 3.1 GLADOS_COOKIES（必填）

对应 GLaDOS 账号 Cookie 中的有效部分，获取方式：

- 在 GLaDOS 签到页面按 `F12`，切换到 `Network` 页面下，刷新
- 点击第一个请求，在 `Request Headers` 下找到 `Cookie`，右键复制其值即可

  > 参考格式：`koa:sess=eyJ1c2xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxAwMH0=; koa:sess.sig=xJkOxxxxxxxxxxxxxxxtnM;`

- 多账号请在 `COOKIES` 中添加多个 cookies，中间使用 `&` 连接即可（例如：`c1&c2&c3`）

![图片加载失败](imgs/2.png)
![图片加载失败](imgs/3.png)

#### 3.2 GLADOS_EXCHANGE_PLAN（非必填）

配置自动兑换积分策略：

| 值 | 积分要求 | 兑换天数 |
|---|---------|---------|
| `plan100` | 100 积分 | 10 天 |
| `plan200` | 200 积分 | 30 天 |
| `plan500` | 500 积分 | 100 天 |

> 不配置时默认不进行自动兑换；如需兑换，设置 `GLADOS_EXCHANGE_PLAN` 为 `plan100` / `plan200` / `plan500`。

#### 3.3 手机推送（非必填）

支持多个推送后端，可在 `Settings`→`Secrets and variables`→`Action` 中按需配置，**任一后端配置后即会推送，支持同时配置多个（都发）**：

- **PushDeer**：添加 `repository secret` 命名为 `PUSHDEER_SENDKEY`，其值对应 PushDeer key（[获取地址](https://www.pushdeer.com/product.html)）。
- **Server酱**：添加 `repository secret` 命名为 `SERVERCHAN_SENDKEY`，其值对应 Server酱 SendKey（[获取地址](https://sct.ftqq.com/)）。
- **企业微信群机器人**：添加 `repository secret` 命名为 `WECOM_WEBHOOK_URL`，其值为机器人的**完整 Webhook URL**，格式如下：

  ```text
  https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的机器人key
  ```

  在企业微信群中添加支持 Webhook 的群机器人并复制地址，然后进入仓库的 `Settings` → `Secrets and variables` → `Actions` → `New repository secret` 保存。URL 包含机器人密钥，请勿写入源码或公开日志。

  仅使用企业微信时，不需要设置 `PUSHDEER_SENDKEY` 和 `SERVERCHAN_SENDKEY`；签到仍需配置 `GLADOS_COOKIES`。保存后进入 `Actions` → `auto check` → `Run workflow` 手动运行，检查群内消息及日志中的推送结果。文本超过 2048 字节时会截断并附带提示，完整签到结果可在 Actions 日志查看。

### 定时运行

`auto check` 工作流显式使用上海时区 `Asia/Shanghai`，使用 cron 表达式 `20 1,5 * * *`，对应北京时间每天 **01:20、05:20**。Fork 后需在 `Actions` 页面启用仓库 Actions，并启用 `auto check` 工作流。

GitHub 的定时事件可能延迟或在高负载时被丢弃，不保证准点触发。判断是否自动运行，请检查运行记录的事件类型是否为 `schedule`；手动运行（`workflow_dispatch`）成功不能证明定时触发正常。需要立即签到时可使用 `Run workflow`。

### Star 本仓库

![图片加载失败](imgs/4.png)

## 更新日志

- **2026-01**: 重构代码，添加日志输出方便定位，支持新版网址，支持配置积分兑换策略。
- **2026-04**: 优化代码逻辑与日志输出，支持[新版域名](https://railgun.info)，在 `GLADOS_COOKIES` 中添加新版域名下的 cookies 即可使用。
- **2026-09**: 设备平台自适应重试（无需手动配置 UA 即可自动恢复签到）；网络层自动重试与退避，降低 CI 网络抖动导致的误报失败；日志时间统一为北京时间，定时任务调整为北京时间每天 2 次并避开整点高峰；默认关闭自动兑换，需显式配置后才启用。
- **2026-10**: 日志级别短标签 `[I]/[W]/[E]` ；推送兼容 Server酱（策略模式多后端「都发」），新增 `requirements.txt` 。

## 问题排查与定位

大家可以通过查询 Actions 中的 running checkin 日志快速定位问题，有其他问题提交 issue。

  <img width="1684" height="844" alt="image" src="https://github.com/user-attachments/assets/45348a5f-43e4-45f5-8fdf-ce84d343b30d" />

## 声明

本项目不保证稳定运行与更新，因 GitHub 相关规定可能会删库，请注意备份。
