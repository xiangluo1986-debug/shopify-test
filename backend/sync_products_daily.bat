@echo off
cd /d "%~dp0"
docker-compose exec -T web python manage.py sync_shopify_products --shop=kidstoylover.myshopify.com
exit /b %errorlevel%
