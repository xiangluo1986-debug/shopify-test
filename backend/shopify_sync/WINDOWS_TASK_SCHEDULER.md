# Shopify Sync Windows Task Scheduler Instructions

当前项目还没有 Celery 或系统级自动调度配置，已提供管理命令和 Windows 计划任务脚本以便手动创建定时任务。

## 目前状态

- 目前自动同步尚未真正启用。
- 现有实现仅包含可手动执行的管理命令：
  - `sync_shopify_products`
  - `sync_shenzhen_orders`
  - `update_shenzhen_tracking`
- 要真正自动同步，需在 Windows Task Scheduler 中创建以下计划任务。

## 已新增脚本

脚本位于 `backend/`：

- `sync_products_daily.bat`
- `sync_shenzhen_orders_30min.bat`
- `update_shenzhen_tracking_30min.bat`

这些脚本会使用 `docker-compose exec -T web` 在容器中执行对应命令。

## 调度建议

- 产品同步：每天 03:00
- 深圳仓订单同步：每 30 分钟
- 深圳仓物流更新：每 30 分钟

## Windows Task Scheduler 任务配置

### 1. 产品同步

- 脚本：`backend\sync_products_daily.bat`
- 触发器：每天
- 开始时间：03:00
- 重复间隔：不重复

### 2. 深圳仓订单同步

- 脚本：`backend\sync_shenzhen_orders_30min.bat`
- 触发器：按计划
- 重复间隔：30 分钟
- 持续时间：无限期

### 3. 深圳仓物流更新

- 脚本：`backend\update_shenzhen_tracking_30min.bat`
- 触发器：按计划
- 重复间隔：30 分钟
- 持续时间：无限期

## 任务设置要点

- “起始路径”应设置为项目根目录：
  - `C:\Users\xiang\OneDrive\桌面\aftersales\backend`
- “程序/脚本”应设置为 `cmd.exe`
- “添加参数”建议填写：
  - `/c sync_products_daily.bat`
  - `/c sync_shenzhen_orders_30min.bat`
  - `/c update_shenzhen_tracking_30min.bat`
- 任务运行前，请确认 Docker Compose 服务已启动：
  - `docker-compose up -d`

## 额外说明

- 这些脚本仅生成了任务入口，真正自动同步需要你在 Windows Task Scheduler 中手动创建任务。
- 服务器重启后，需要确认 Docker 容器和计划任务仍然正常运行。