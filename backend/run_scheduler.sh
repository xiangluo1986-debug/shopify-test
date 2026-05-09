#!/usr/bin/env bash

# Shopify Sync Scheduler
# 执行周期：
# - 每 30 分钟：订单同步 + 物流更新
# - 每天凌晨 3:00：产品同步

set +e  # 不在第一个错误时退出

LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/scheduler.log"

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log_message "Scheduler started"

# 记录最后执行的时间戳（文件）
LAST_PRODUCT_SYNC_FILE="/tmp/last_product_sync"
LAST_ORDERS_SYNC_FILE="/tmp/last_orders_sync"

# 初始化
touch "$LAST_PRODUCT_SYNC_FILE"
touch "$LAST_ORDERS_SYNC_FILE"

while true; do
    CURRENT_HOUR=$(date +%H)
    CURRENT_MINUTE=$(date +%M)
    CURRENT_DATE=$(date +%Y-%m-%d)
    
    # 每天凌晨 3:00 执行产品同步（仅在 3:00-3:29 分钟范围内执行一次）
    if [ "$CURRENT_HOUR" -eq 3 ] && [ "$CURRENT_MINUTE" -lt 30 ]; then
        LAST_SYNC_DATE=$(cat "$LAST_PRODUCT_SYNC_FILE" 2>/dev/null || echo "")
        if [ "$LAST_SYNC_DATE" != "$CURRENT_DATE" ]; then
            log_message "执行产品同步..."
            python manage.py sync_shopify_products --shop=kidstoylover.myshopify.com --skip-if-success-today >> "$LOG_FILE" 2>&1
            SYNC_EXIT_CODE=$?
            if [ $SYNC_EXIT_CODE -eq 0 ]; then
                log_message "产品同步成功"
                echo "$CURRENT_DATE" > "$LAST_PRODUCT_SYNC_FILE"
            else
                log_message "产品同步失败 (exit code: $SYNC_EXIT_CODE)，但继续运行"
            fi
        fi
    fi
    
    # 每 30 分钟执行订单同步和物流更新（检查分钟是否是 0 或 30）
    if [ "$CURRENT_MINUTE" -eq 0 ] || [ "$CURRENT_MINUTE" -eq 30 ]; then
        log_message "执行订单同步..."
        if [ "$CURRENT_HOUR" -ge 3 ]; then
            log_message "Check daily product sync..."
            python manage.py sync_shopify_products --shop=kidstoylover.myshopify.com --skip-if-success-today >> "$LOG_FILE" 2>&1
            PRODUCT_DAILY_EXIT=$?
            if [ $PRODUCT_DAILY_EXIT -eq 0 ]; then
                log_message "Daily product sync check completed"
            else
                log_message "Daily product sync check failed (exit code: $PRODUCT_DAILY_EXIT), continuing"
            fi
        fi

        python manage.py sync_shenzhen_orders --shop=kidstoylover.myshopify.com --days=3 >> "$LOG_FILE" 2>&1
        ORDERS_SYNC_EXIT=$?
        if [ $ORDERS_SYNC_EXIT -eq 0 ]; then
            log_message "订单同步成功"
        else
            log_message "订单同步失败 (exit code: $ORDERS_SYNC_EXIT)，但继续运行"
        fi
        
        log_message "执行物流更新..."
        python manage.py update_shenzhen_tracking --shop=kidstoylover.myshopify.com >> "$LOG_FILE" 2>&1
        TRACKING_EXIT=$?
        if [ $TRACKING_EXIT -eq 0 ]; then
            log_message "物流更新成功"
        else
            log_message "物流更新失败 (exit code: $TRACKING_EXIT)，但继续运行"
        fi
        
        # 计算下一次执行时间
        NEXT_MINUTE=$((CURRENT_MINUTE + 30))
        if [ $NEXT_MINUTE -ge 60 ]; then
            NEXT_MINUTE=$((NEXT_MINUTE - 60))
            NEXT_HOUR=$((CURRENT_HOUR + 1))
            if [ $NEXT_HOUR -ge 24 ]; then
                NEXT_HOUR=0
            fi
        else
            NEXT_HOUR=$CURRENT_HOUR
        fi
        log_message "下一次订单同步将在 $(printf '%02d:%02d' $NEXT_HOUR $NEXT_MINUTE) 执行"
        
        # 等待直到分钟不再是 0 或 30，避免重复执行
        sleep 70
    else
        # 每 30 秒检查一次，计算距离下一个同步点还有多少时间
        MINUTES_TO_SYNC=$((30 - (CURRENT_MINUTE % 30)))
        if [ $MINUTES_TO_SYNC -eq 30 ]; then
            MINUTES_TO_SYNC=0
        fi
        SECONDS_TO_SYNC=$((MINUTES_TO_SYNC * 60))
        log_message "距离下一次订单同步还有 $MINUTES_TO_SYNC 分 $(date +%S) 秒，继续等待中..."
        
        # 短睡眠，定期检查
        sleep 30
    fi
done
