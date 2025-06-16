#!/usr/bin/env python3.12

import asyncio
import logging
import sys
from aiog import *
import init_clients


async def main() -> None:
    try:
        await init_clients.dp.start_polling(init_clients.bot)
    except asyncio.CancelledError:
        print("Обработка запросов отменена")
    except aiogram.exceptions.TelegramRetryAfter:
        print("Отключился от телеграм")
    finally:
        await init_clients.bot.close()
        await init_clients.dp.storage.close()


if __name__ == "__main__":
    try:
        fh = logging.FileHandler('runtime.log')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s %(levelname)s\t%(name)s %(message)s')
        fh.setFormatter(formatter)

        loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
        for logger in loggers:
            if logger.name == "aiogram":
                continue
            logger.addHandler(fh)

        logging.basicConfig(level=logging.INFO, stream=sys.stdout)
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
