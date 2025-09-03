from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.asyncio import AsyncIOExecutor

from main import logger


class SchedulerManager:
    def __init__(self):
        self.scheduler = None

    def setup(self):
        """Настройка планировщика"""
        try:
            import editabs

            self.scheduler = AsyncIOScheduler(
                executors={'default': AsyncIOExecutor()},
                timezone='Europe/Moscow'
                )

            self.scheduler.add_job(
                func=editabs.clear_zakupkigov,
                trigger=CronTrigger(hour=0, minute=5),
                id='daily_cleanup',
                name='Ежедневная очистка zakupkigov',
                replace_existing=True,
                max_instances=1
                )

            logger.info("📅 Планировщик настроен:")
            logger.info("Ежедневная очистка: каждый день в 00:05")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка при настройке планировщика: {e}")
            return False

    def start(self):
        """Запуск планировщика"""
        try:
            if self.scheduler is None:
                logger.info("❌ Планировщик не настроен")
                return False

            if not self.scheduler.running:
                self.scheduler.start()
                logger.info("🎯 Планировщик запущен")
                return True
            else:
                logger.info("ℹ️ Планировщик уже запущен")
                return True

        except Exception as e:
            logger.error(f"❌ Ошибка при запуске планировщика: {e}")
            return False
