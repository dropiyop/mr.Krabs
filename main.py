#!/usr/bin/env python3.12
import asyncio
import signal
import sys
from contextlib import suppress
from select import error
import init_clients
from handlers import *
import datetime
import  logging
from logging.handlers import RotatingFileHandler
import os
from database import *

init_db()

# Настройка логирования
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# Настройка форматирования логов
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Создаем форматтер
formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

# Получаем корневой логгер
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Очищаем существующие обработчики
logger.handlers.clear()

# Консольный обработчик
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)



# Файловый обработчик с ротацией по размеру
file_handler = RotatingFileHandler(
    filename=os.path.join(LOG_DIR, 'bot.log'),
    maxBytes=10*1024*1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Файловый обработчик для ошибок
error_handler = RotatingFileHandler(
    filename=os.path.join(LOG_DIR, 'bot_errors.log'),
    maxBytes=5*1024*1024,  # 5 MB
    backupCount=3,
    encoding='utf-8'
)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(formatter)
logger.addHandler(error_handler)


# Глобальный флаг для остановки
shutdown_event = asyncio.Event()


def signal_handler():
    """Обработчик сигналов завершения"""
    logging.info("Получен сигнал завершения, останавливаем бота...")
    shutdown_event.set()


async def periodic_checks():
    """Запускает все периодические проверки параллельно"""
    while not shutdown_event.is_set():
        try:
            # Проверяем текущее время
            now = datetime.datetime.now()
            current_time = now.time()

            # Определяем запрещенный диапазон: 00:00 - 00:15
            start_blocked = datetime.time(0, 0)  # 00:00
            end_blocked = datetime.time(0, 15)  # 00:15

            if start_blocked <= current_time <= end_blocked:
                logging.info(f"Время {current_time.strftime('%H:%M:%S')} в заблокированном диапазоне 00:00-00:15. Задачи пропущены.")
            else:
                logging.info(f"Время {current_time.strftime('%H:%M:%S')} - выполняем периодические задачи")

                # Запускаем задачи
                tasks = [
                    asyncio.create_task(zakupki.periodic_check()),
                    asyncio.create_task(mimz.periodic_check_mimz()),
                    asyncio.create_task((zakupki_all_regions.periodic_check_all_regions())),
                    asyncio.create_task((eat.periodic_check_eat()))
                    ]

                # Ждем завершения всех задач
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Проверяем результаты
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logging.error(f"Ошибка в задаче {i}: {result}")

            # Ждем 60 секунд перед следующей проверкой (или настройте по необходимости)
            await asyncio.sleep(60)

        except Exception as e:
            logging.error(f"Ошибка в periodic_checks: {e}", exc_info=True)
            await asyncio.sleep(60)  # Ждем минуту перед повтором


async def main():
    logging.info("=" * 50)
    logging.info("Запуск бота")
    logging.info(f"Версия Python: {sys.version}")
    logging.info(f"Платформа: {sys.platform}")
    logging.info("=" * 50)

    # Настройка планировщика
    try:
        scheduler_manager = sheduler.SchedulerManager()
        scheduler_manager.setup()
        scheduler_manager.start()
        logging.info("Планировщик запущен")
    except Exception as e:
        logging.error(f"Ошибка при запуске планировщика: {e}", exc_info=True)

    # Устанавливаем обработчики сигналов
    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)
    else:
        # Для Windows
        signal.signal(signal.SIGINT, lambda s, f: signal_handler())

    try:
        # Создаем фоновую задачу для периодических проверок
        periodic_task = asyncio.create_task(periodic_checks())
        logging.info("Запущена фоновая задача периодических проверок")

        # Запускаем polling бота
        logging.info("Запуск polling бота...")
        polling_task = asyncio.create_task(
            init_clients.dp.start_polling(
                init_clients.bot,
                handle_signals=False  # Отключаем встроенную обработку сигналов
                )
            )

        logging.info("Бот запущен и готов к работе!")

        # Ждем сигнал завершения
        await shutdown_event.wait()

        logging.info("Останавливаем периодические задачи...")
        periodic_task.cancel()

        logging.info("Останавливаем polling...")
        await init_clients.dp.stop_polling()

    except Exception as e:
        logging.error(f"Критическая ошибка в main: {e}", exc_info=True)

    finally:
        logging.info("Закрываем сессию бота...")
        await init_clients.bot.session.close()

        # Даем время на завершение всех задач
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        if pending:
            logging.info(f"Отменяем {len(pending)} незавершенных задач...")
            for task in pending:
                task.cancel()

            with suppress(asyncio.CancelledError):
                await asyncio.gather(*pending)

        logging.info("Бот остановлен")
        logging.info("=" * 50)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен пользователем (KeyboardInterrupt)")
    except Exception as e:
        logging.critical(f"Неожиданная ошибка: {e}", exc_info=True)
        sys.exit(1)