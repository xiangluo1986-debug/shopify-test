@echo off
cd /d "%~dp0"
docker-compose exec -T web python manage.py sync_shenzhen_orders --shop=kidstoylover.myshopify.com --days=60
exit /b %errorlevel%
